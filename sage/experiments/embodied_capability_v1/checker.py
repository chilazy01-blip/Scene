"""Evidence-scoped capability queries. No extrapolation or hardware upgrades."""
from collections import Counter
import math


def wilson(successes, attempts, z=1.959963984540054):
    if not 0<=successes<=attempts:raise ValueError('invalid_denominator')
    if not attempts:return None
    rate=successes/attempts;den=1+z*z/attempts
    center=(rate+z*z/(2*attempts))/den
    radius=z*math.sqrt(rate*(1-rate)/attempts+z*z/(4*attempts*attempts))/den
    return [max(0.,center-radius),min(1.,center+radius)]


class CapabilityIndex:
    """Exact condition identity must include model/controller/task bindings.

    Missing terminal evidence counts as attempted/unknown, never a success.
    Intervals are descriptive Bernoulli summaries, not a claim that repeated
    deterministic episodes are independent physical observations.
    """
    def __init__(self,records):
        self.records=list(records)
        ids=[r['trial_id'] for r in self.records]
        if len(ids)!=len(set(ids)):raise ValueError('duplicate_trial_identity')
        for r in self.records:
            for field in ('condition_id','scope','kind','attempted','terminal','passed'):
                if field not in r:raise ValueError('missing_'+field)
            if r['scope']!='simulation_only':raise ValueError('unsupported_evidence_scope')
            if r['passed'] and (not r['attempted'] or not r['terminal'] or not r.get('audit_passed')):
                raise ValueError('unverified_success')
    def query(self,condition_id,*,request_scope='simulation_only',kind='complete_task_baseline'):
        if request_scope!='simulation_only':
            return dict(status='unknown',reason='no_real_hardware_validation',attempts=0,qualified=False)
        rows=[r for r in self.records if r['condition_id']==condition_id and r['kind']==kind]
        attempted=[r for r in rows if r['attempted']]
        if not attempted:return dict(status='unknown',reason='condition_not_covered',attempts=0,qualified=False)
        succeeded=sum(r['passed'] and r.get('audit_passed',False) for r in attempted)
        failed=sum(r['terminal'] and not r['passed'] for r in attempted)
        incomplete=len(attempted)-succeeded-failed
        failures=Counter(f for r in attempted for f in r.get('failures',[]))
        return dict(status='observed_success' if succeeded else ('observed_failure' if failed else 'unknown'),scope='simulation_only',attempts=len(attempted),successes=succeeded,failures=failed,incomplete=incomplete,success_rate=succeeded/len(attempted),descriptive_wilson95=wilson(succeeded,len(attempted)),failure_reasons=dict(failures),qualified=False,interpretation='Specified controller and exact recorded conditions only; not robot impossibility, generalization, hardware validity or learning benefit',independent_samples_not_assumed=True)
    def summary(self):
        keys=sorted(set((r['condition_id'],r['kind']) for r in self.records))
        return [dict(condition_id=k,kind=t,**self.query(k,kind=t)) for k,t in keys]
