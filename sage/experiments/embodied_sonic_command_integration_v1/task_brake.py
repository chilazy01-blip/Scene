"""Earlier base/arm handoff after actual required transport, retaining original task goals."""
from .task_envelope import Task as Previous

def should_brake(task,data):
    return task.stage=='carry' and not task.failure and task.carry_origin is not None and data.qpos[0]-task.carry_origin[0]>=.25 and all(task.carry_cycles[s]>=1 for s in ('left','right'))

class Task(Previous):
    def update(self,tick,data,m):
        super().update(tick,data,m)
        if should_brake(self,data):
            self.events.append(dict(kind='required_real_transport_base_arm_handoff',tick=tick,forward_carry_m=float(data.qpos[0]-self.carry_origin[0]),foot_cycles=self.carry_cycles.copy(),original_object_goal_unchanged=True,original75tick_brake=True))
            self.change('target_stop',tick,data,m)
            self.stop(tick)
