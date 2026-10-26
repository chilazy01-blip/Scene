"""Keep all old action costs; two new slots require the exact new approval."""
from .runtime import J,N,F,read,digest
from sage.experiments.embodied_fb2_repair_v1.stop_trim_quota import StopTrimQuota
from sage.experiments.embodied_task_space_v6.durable_quota_r2 import Journal

class NativeQuota:
    def __init__(self):
        auth=read(J/'AUTHORIZATION.json'); h=digest(J/'APPROVED_PROPOSAL.json')
        assert auth['proposal_sha256']==h and auth['additional_component_allowance']==2
        self.base=StopTrimQuota(N,F)
        try:
            self.extra=Journal(J/'ACTION_JOURNAL.jsonl','native-source:'+h,
                dict(component_attempts=2,physics_steps=16000,dynamic_policy_forwards=3300,
                     static_policy_forwards=256,render_passes=5200))
        except BaseException:self.base.close();raise
    @property
    def used(self):
        values=dict(self.base.used)
        values['component_attempts']+=self.extra.used['component_attempts']
        return values
    @property
    def completed(self):return self.base.completed
    def claim(self,name,kind,binding):
        if kind=='component_attempts':return self.extra.claim(name,kind,binding)
        return self.base.claim(name,kind,binding)
    def reserve(self,kind,units=1):
        # Both stage and old cumulative quotas reserve BEFORE every action.
        a=self.extra.reserve(kind,units)
        b=self.base.reserve(kind,units)
        return a,b
    def complete(self,tokens):
        self.base.complete(tokens[1]);self.extra.complete(tokens[0])
    def close(self):self.extra.close();self.base.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
