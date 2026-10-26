"""Seek explicit soft interior room in already qualified terminal phases.

All original hard constraints, path representation, native 6 mm gates,
acceptance rules, witness history and search budgets remain unchanged.
"""
import numpy as np
from sage.experiments.embodied_task_space_v9.template_compiler_r3 import Compiler as Base,solve_qp

class Compiler(Base):
    def problem(self,x,linear,trust):
        cost,A,lo,hi=super().problem(x,linear,trust)
        original=hi;hi=hi.copy();columns=A.tocsc();changed=[];phases=[]
        for i,phase in enumerate(self.current['meta']['phases']):
            if not phase['passed'] or phase['endpoint_palm_error']<=.0055:continue
            group=self.map.size+60+2*i
            col=columns[:,group].tocoo();rows=col.row[col.data==-1.]
            if not len(rows):raise ValueError('qualified_soft_palm_rows_missing')
            hi[rows]-=.0005/.006;changed.extend(rows.tolist());phases.append(i)
        untouched=np.ones(len(hi),dtype=bool);untouched[changed]=False
        assert np.array_equal(hi[untouched],original[untouched])
        self.objective_record.update(qualified_phase_soft_interior_m=.0005,qualified_phase_interior_trigger_m=.0055,interior_phase_indices=phases,interior_soft_rows=len(changed),original_hard_bounds_retained=True)
        return cost,A,lo,hi
