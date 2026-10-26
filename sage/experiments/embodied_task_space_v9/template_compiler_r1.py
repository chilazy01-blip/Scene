"""Gate-restoration solver with an explicitly complete condition-adaptation map."""
from sage.experiments.embodied_task_space_v8.gate_compiler_r3 import Compiler as Base,solve_qp

class Compiler(Base):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.map.plan['active_phases']!=list(range(15)) or len(self.map.frozen_variables):
            raise ValueError('whole_condition_adaptation_required')
