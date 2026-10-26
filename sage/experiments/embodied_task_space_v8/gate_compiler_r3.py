"""Equivalent conservative broad phase and shared sparse reference embedding."""
import numpy as np
from .gate_compiler_r1 import Compiler as Base,solve_qp
from .gate_linearization_r3 import linearize_terminal_window

class Compiler(Base):
    def linearize_hierarchy(self,x,selected,stop_selected):
        ticks,stops=self.contact_witnesses.selections(selected,stop_selected)
        result=linearize_terminal_window(self,x,ticks,stops)
        d=result['descriptors'];emitted={(int(r[0]),int(r[1])) for r in d if r[1]>0}
        record=dict(observations=self.contact_witnesses.observations,selected_ticks=len(ticks),requested_stopping_states=len(stops),emitted_stopping_states=len(emitted),requested_stops_without_contact_rows=[list(v) for v in sorted(stops-emitted)],contact_rows=len(d),release_stopping_rows=int(np.sum((d[:,0]>=self.map.offsets[11])&(d[:,0]<self.map.offsets[12])&(d[:,1]>0))),terminal_hold_after_current_stop=True,terminal_task_samples=len(result['endpoints']))
        self.witness_linearizations.append(record)
        return result

