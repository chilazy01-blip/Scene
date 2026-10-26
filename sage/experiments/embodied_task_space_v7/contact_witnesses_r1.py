"""Monotone memory of contact locations from every completely audited trial."""
from numbers import Integral

class WitnessRejected(ValueError):
    pass

class ContactWitnesses:
    def __init__(self,states):
        if not isinstance(states,Integral) or isinstance(states,bool) or states<=0:
            raise WitnessRejected('complete_reference_clock_required')
        self.states=int(states);self.current_ticks=set();self.stopping_states=set();self.observations=0

    def observe(self,evaluation):
        if evaluation.get('meta',{}).get('states')!=self.states or not all(k in evaluation for k in ['bad','stops','worst']):
            raise WitnessRejected('complete_audit_evaluation_required')
        ticks=set();stops=set()
        for row in evaluation['bad']:
            tick=row.get('tick')
            if not isinstance(tick,Integral) or isinstance(tick,bool) or not 0<=tick<self.states:
                raise WitnessRejected('invalid_current_tick')
            ticks.add(int(tick))
        # The same role-wise worst-stop selector as the frozen method is used.
        # The difference is that rejected trials also contribute permanently.
        for tick,step in evaluation['worst']:
            if not isinstance(tick,Integral) or isinstance(tick,bool) or not 0<=tick<self.states:
                raise WitnessRejected('invalid_stop_tick')
            if not isinstance(step,Integral) or isinstance(step,bool) or not 1<=step<=36:
                raise WitnessRejected('stop_step_outside_original_velocity_acceleration_domain')
            stops.add((int(tick),int(step)))
        # Validate the entire observation before mutating accumulated evidence.
        before=(len(self.current_ticks),len(self.stopping_states))
        self.current_ticks.update(ticks);self.stopping_states.update(stops);self.observations+=1
        return dict(added_current_ticks=len(self.current_ticks)-before[0],added_stopping_states=len(self.stopping_states)-before[1])

    def selections(self,selected,stop_selected):
        stops=set(stop_selected)|self.stopping_states
        ticks=set(selected)|self.current_ticks|{tick for tick,step in stops}
        return ticks,stops

    def snapshot(self):
        return dict(states=self.states,observations=self.observations,current_ticks=sorted(self.current_ticks),stopping_states=[list(v) for v in sorted(self.stopping_states)],selection_grants_success=False)
