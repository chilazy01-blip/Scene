"""Prepared successor: retain stopping witnesses from rejected audited trials.

The curve chart, QP, six-iteration budget, stopping law, protected acceptance
filter and independent final gates are inherited unchanged. This module does
not admit execution or reset a case budget. Current U evidence remains frozen.
"""
import numpy as np
from sage.experiments.embodied_task_space_v6.local_compiler_r2 import Compiler as Base
from .contact_witnesses_r1 import ContactWitnesses

class Compiler(Base):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.contact_witnesses=ContactWitnesses(self.map.n)
        self.witness_linearizations=[]

    def evaluate(self,x):
        result=super().evaluate(x)
        self.contact_witnesses.observe(result)
        return result

    def linearize_hierarchy(self,x,selected,stop_selected):
        ticks,stops=self.contact_witnesses.selections(selected,stop_selected)
        result=super().linearize_hierarchy(x,ticks,stops)
        descriptors=result['descriptors'];emitted={(int(r[0]),int(r[1])) for r in descriptors if r[1]>0}
        # Missing descriptors may mean a shorter stopping horizon or inactive
        # contact pairs at the incumbent. Preserve this limitation explicitly;
        # the complete nonlinear audit still decides every trial's validity.
        record=dict(observations=self.contact_witnesses.observations,selected_ticks=len(ticks),requested_stopping_states=len(stops),emitted_stopping_states=len(emitted),requested_stops_without_contact_rows=[list(v) for v in sorted(stops-emitted)],contact_rows=len(descriptors),release_stopping_rows=int(np.sum((descriptors[:,0]>=self.map.offsets[11])&(descriptors[:,0]<self.map.offsets[12])&(descriptors[:,1]>0))))
        self.witness_linearizations.append(record)
        return result
