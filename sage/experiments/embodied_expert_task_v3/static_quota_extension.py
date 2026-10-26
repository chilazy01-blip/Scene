"""Add an explicitly approved static-only allowance without rewriting old history."""
from pathlib import Path
import hashlib,json
from sage.experiments.embodied_task_space_v6.durable_quota_r2 import Journal,QuotaRejected

class StaticExtensionQuota:
    def __init__(self,base,extension=None):self.base=base;self.extension=extension
    @property
    def used(self):
        result=dict(self.base.used)
        if self.extension:result['static_policy_forwards']+=self.extension.used['static_policy_forwards']
        return result
    @property
    def completed(self):
        result=dict(self.base.completed)
        if self.extension:result['static_policy_forwards']+=self.extension.completed['static_policy_forwards']
        return result
    @property
    def limits(self):
        result=dict(self.base.limits)
        if self.extension:result['static_policy_forwards']+=self.extension.limits['static_policy_forwards']
        return result
    def reserve(self,kind,units=1):
        if kind=='static_policy_forwards' and self.base.used[kind]+units>self.base.limits[kind]:
            if self.extension is None:raise QuotaRejected('new_static_allowance_not_authorized')
            return self.extension.reserve(kind,units)
        return self.base.reserve(kind,units)
    def complete(self,token):
        if token in self.base.pending:self.base.complete(token)
        elif self.extension and token in self.extension.pending:self.extension.complete(token)
        else:raise QuotaRejected('unknown_or_repeated_completion')
    def claim(self,*args,**kwargs):return self.base.claim(*args,**kwargs)
    def close(self):
        if self.extension:self.extension.close()
        self.base.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

def open_current(root,enable_extension=False):
    n=Path(root);read=lambda p:json.loads(p.read_text());b=read(n/'prepared/local_refinement_v6/ACTION_ACCOUNTING_BASELINE.json');limits=read(n/'whole_template_transfer_v9/protocol/ACTION_AUTHORITY_R2.json')['limits'];extension=None
    base=Journal(b['journal_path'],b['journal_scope'],limits)
    try:
        if enable_extension:
            directory=n/'prepared/phase_feedback_20261007/static_extension_r1';proposal=directory/'RESOURCE_PROPOSAL.json';sha=hashlib.sha256(proposal.read_bytes()).hexdigest();p=read(proposal);approval_path=directory/'USER_APPROVAL.json'
            if not approval_path.exists():raise QuotaRejected('new_static_allowance_not_authorized')
            a=read(approval_path)
            if not (a.get('approved') is True and a.get('proposal_sha256')==sha and a.get('source')=='explicit_user_message' and a.get('user_reply') and a.get('increase')==p['requested_static_increase']==8000 and a.get('new_static_cap')==p['proposed_static_cap']==92000):raise QuotaRejected('invalid_static_extension_approval')
            assert limits['static_policy_forwards']==84000
            extension=Journal(directory/'STATIC_EXTENSION_QUOTA.jsonl','fb2_static_extension_r1:'+sha,dict(static_policy_forwards=8000))
        return StaticExtensionQuota(base,extension)
    except BaseException:
        if extension:extension.close()
        base.close();raise
