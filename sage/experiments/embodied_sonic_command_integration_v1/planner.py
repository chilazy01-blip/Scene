"""Optional real planner adapter; current task keeps its frozen walking reference."""
from pathlib import Path
import numpy as np
from sage.experiments.embodied_data_stability_v1 import sonic_native_planner_preflight as official
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import _make_session

class PlannerSource:
    def __init__(self,path):self.session=_make_session(Path(path))
    def plan(self,context,**command):
        inputs=official.build_planner_inputs(context,**command)
        q,count,wall=official._run_once(self.session,inputs)
        valid,_,metrics=official.validate_planner_outputs(q,count)
        motion=official.resample_qpos_50hz(valid)
        if len(motion)<2:raise ValueError('planner returned no usable horizon')
        return motion,dict(metrics,inference_wall_s=wall,control_hz=50,new_physics_steps=0)
    @staticmethod
    def next_context(motion):return official.context_from_motion_50hz(motion)
