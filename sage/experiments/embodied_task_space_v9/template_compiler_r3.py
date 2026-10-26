"""Complete condition adaptation with exact coefficient-preserving retiming."""
from types import SimpleNamespace
import numpy as np
from sage.experiments.embodied_task_space_v8.gate_compiler_r3 import Compiler as Base,solve_qp
from sage.experiments.embodied_task_space_v7.contact_witnesses_r1 import ContactWitnesses
from .retimed_template_r2 import condition_map

class Compiler(Base):
    def __init__(self,c,active,residual,sources,stages,spec,plan,original_variables,anchor):
        nominal_rows=spec['template_source_rows']
        if len(nominal_rows)!=15:raise ValueError('complete_nominal_source_counts_required')
        proxies=[SimpleNamespace(rows=int(r)) for r in nominal_rows]
        super().__init__(c,active,residual,proxies,stages,spec,plan,original_variables,anchor)
        self.sources=sources
        self.map,self.extra_source_ticks=condition_map(self.original_map,plan,original_variables,anchor,sources)
        self.phase_of=np.repeat(np.arange(len(stages)),np.diff(self.map.offsets))
        self.local=np.concatenate([np.arange(n) for n in np.diff(self.map.offsets)])
        self.contact_witnesses=ContactWitnesses(self.map.n)
        if plan['active_phases']!=list(range(15)) or len(self.map.frozen_variables):
            raise ValueError('whole_condition_adaptation_required')
