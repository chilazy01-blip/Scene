"""No further physical trial before an explicit decision on the prepared scope."""
from pathlib import Path
import json,hashlib
from .continuation_quota import ContinuationQuota as RepairQuota
from sage.experiments.embodied_task_space_v6.durable_quota_r2 import Journal


def require_authorization(repair):
    p=Path(repair);authorization=p/'STOP_TRIM_AUTHORIZATION_R1.json'
    if not authorization.exists():raise RuntimeError('additional_component_scope_not_authorized')
    a=json.loads(authorization.read_text())
    h=hashlib.sha256((p/'STOP_TRIM_PROPOSAL_R1.json').read_bytes()).hexdigest()
    if a.get('proposal_sha256')!=h or a.get('additional_component_allowance')!=1 or not a.get('user_reply'):
        raise RuntimeError('invalid_additional_component_authorization')
    return h


class StopTrimQuota:
    def __init__(self,root,repair):
        h=require_authorization(repair)
        self.base=RepairQuota(root,repair)
        try:self.extra=Journal(Path(repair)/'STOP_TRIM_COMPONENTS.jsonl','fb2-root-repair-stop-trim:'+h,dict(component_attempts=1))
        except BaseException:self.base.close();raise
    @property
    def used(self):
        result=dict(self.base.used);result['component_attempts']+=self.extra.used['component_attempts'];return result
    @property
    def completed(self):return self.base.completed
    def reserve(self,*args):return self.base.reserve(*args)
    def complete(self,*args):return self.base.complete(*args)
    def claim(self,name,kind,binding):
        if kind=='component_attempts':return self.extra.claim(name,kind,binding)
        return self.base.claim(name,kind,binding)
    def close(self):self.extra.close();self.base.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
