"""Arm clearance correction only: tuck beside body before approach, reach after stop."""
import numpy as np
from .task_v3 import Task as ParentTask, smooth
from sage.experiments.embodied_transport_hybrid_v1.control import ARM
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native


class Task(ParentTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.approach_tuck_started = False

    def update(self, tick, data, metrics):
        if self.stage == 'initial_stand' and not self.failure:
            if tick >= 100 and not self.approach_tuck_started:
                self.approach_tuck_started = True
                origin=data.qpos[self.armq].copy()
                middle=origin.copy();middle[1]=-.6
                final=np.array([.75,-.25,0,1.2,0,0,0])
                age=np.arange(len(self.q)-tick)
                first=smooth(age/40)[:,None];second=smooth((age-40)/60)[:,None]
                self.q[tick:,ARM+7]=np.where((age<40)[:,None],(1-first)*origin+first*middle,(1-second)*middle+second*final)
                self.v=native._reference_velocities(self.q)
                self.events.append(dict(kind='prewalk_tucked_arm_path',tick=tick,
                    origin_rad=origin.tolist(),middle_rad=middle.tolist(),target_rad=final.tolist(),
                    segment_ticks=[40,60],walk_earliest_tick=225))
            # Preserve the original initial100 ticks and perform bounded arm retraction
            # while standing. Original initial_stand timeout still applies thereafter.
            if 100 <= tick < 225:
                return
        return super().update(tick,data,metrics)
