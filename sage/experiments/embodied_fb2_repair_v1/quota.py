"""Append the user-authorized three component slots to the persistent base ledger."""
from pathlib import Path
import json,hashlib
from sage.experiments.embodied_expert_task_v3.static_quota_extension import open_current
from sage.experiments.embodied_task_space_v6.durable_quota_r2 import Journal


class RepairQuota:
    def __init__(self,root,repair):
        self.base=open_current(root,enable_extension=True)
        p=Path(repair)
        try:
            a=json.loads((p/'USER_AUTHORIZATION_R1.json').read_text())
            h=hashlib.sha256((p/'PLAN_R1.json').read_bytes()).hexdigest()
            assert a['proposal_sha256']==h and a['additional_component_allowance']==3 and a['user_reply']
            self.extra=Journal(p/'COMPONENT_EXTENSION.jsonl','fb2_root_repair_components:'+h,dict(component_attempts=3))
        except BaseException:self.base.close();raise
    @property
    def used(self):
        r=dict(self.base.used);r['component_attempts']+=self.extra.used['component_attempts'];return r
    @property
    def completed(self):return self.base.completed
    def reserve(self,*args):return self.base.reserve(*args)
    def complete(self,*args):return self.base.complete(*args)
    def claim(self,name,kind,binding):
        if kind=='component_attempts' and self.base.used[kind]>=self.base.limits[kind]:
            return self.extra.claim(name,kind,binding)
        return self.base.claim(name,kind,binding)
    def close(self):self.extra.close();self.base.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
