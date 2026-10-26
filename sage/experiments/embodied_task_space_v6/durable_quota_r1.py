"""Append-only cumulative reservations for prospectively admitted work.

A reservation is charged before an external action. Uncommitted reservations
remain charged after interruption. This module never grants scientific or
resource admission; callers must pass the separate gates first. The journal
belongs to the persistent authorization scope, never to a renamed worker.
"""
from pathlib import Path
import fcntl,hashlib,json,os


class QuotaRejected(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


class Journal:
    def __init__(self,path,scope,limits):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        if not isinstance(scope,str) or not scope or not limits:raise QuotaRejected('scope_and_limits_required')
        if any(not isinstance(k,str) or type(v) is not int or v<0 for k,v in limits.items()):raise QuotaRejected('invalid_limits')
        self.scope=scope;self.limits=dict(limits);self.used={k:0 for k in limits};self.completed={k:0 for k in limits};self.pending={};self.claims={};self.sequence=0;self.previous='0'*64
        self.lock=self.path.with_suffix(self.path.suffix+'.lock').open('a+b');self.stream=None
        try:
            fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if self.path.exists():
                with self.path.open('rb') as source:
                    for raw in source:
                        if not raw.endswith(b'\n'):raise QuotaRejected('truncated_journal_requires_reconciliation')
                        try:record=json.loads(raw)
                        except ValueError as exc:raise QuotaRejected('invalid_journal') from exc
                        self._accept(record)
            self.stream=self.path.open('ab',buffering=0)
            if self.sequence==0:self._append(dict(event='open',scope=scope,limits=limits))
        except BaseException:
            if self.stream is not None:self.stream.close()
            self.lock.close();raise

    def _accept(self,record):
        body={k:v for k,v in record.items() if k!='sha256'}
        if record.get('sequence')!=self.sequence or record.get('previous')!=self.previous or record.get('sha256')!=hashlib.sha256(canonical(body)).hexdigest():raise QuotaRejected('journal_chain_changed')
        event=record.get('event')
        if self.sequence==0:
            if event!='open' or record.get('scope')!=self.scope or record.get('limits')!=self.limits:raise QuotaRejected('persistent_scope_or_limits_changed')
        elif event=='reserve':
            kind=record['kind'];units=record['units'];token=record['token']
            if kind not in self.used or type(units) is not int or units<=0 or token in self.pending:raise QuotaRejected('invalid_reservation')
            if self.used[kind]+units>self.limits[kind]:raise QuotaRejected('cumulative_quota_exceeded:'+kind)
            self.used[kind]+=units;self.pending[token]=(kind,units)
        elif event=='complete':
            token=record['token']
            if token not in self.pending:raise QuotaRejected('unknown_or_repeated_completion')
            kind,units=self.pending.pop(token);self.completed[kind]+=units
        elif event=='claim':
            name=record['name'];kind=record['kind']
            if name in self.claims or kind not in self.used or self.used[kind]+1>self.limits[kind]:raise QuotaRejected('claim_consumed_or_quota_exceeded')
            self.claims[name]=record['binding_sha256'];self.used[kind]+=1
        else:raise QuotaRejected('unexpected_journal_event')
        self.sequence+=1;self.previous=record['sha256']

    def _append(self,event):
        body=dict(event,sequence=self.sequence,previous=self.previous);record=dict(body,sha256=hashlib.sha256(canonical(body)).hexdigest())
        # Validate against an isolated copy before appending a durable record.
        snapshot=(dict(self.used),dict(self.completed),dict(self.pending),dict(self.claims),self.sequence,self.previous)
        try:self._accept(record)
        except BaseException:
            self.used,self.completed,self.pending,self.claims,self.sequence,self.previous=snapshot;raise
        try:
            payload=canonical(record)+b'\n';written=self.stream.write(payload)
            if written!=len(payload):raise OSError('partial_journal_write')
            os.fsync(self.stream.fileno())
        except BaseException:
            # The action must not start. Reopen and reconcile actual durable
            # bytes; never continue using in-memory counters after I/O error.
            self.close();raise
        return record

    def reserve(self,kind,units=1):
        token=self.scope+':'+str(self.sequence)
        self._append(dict(event='reserve',kind=kind,units=units,token=token));return token

    def complete(self,token):
        self._append(dict(event='complete',token=token))

    def claim(self,name,kind,binding_sha256):
        if not isinstance(name,str) or not name or not isinstance(binding_sha256,str) or len(binding_sha256)!=64:raise QuotaRejected('claim_identity_required')
        self._append(dict(event='claim',name=name,kind=kind,binding_sha256=binding_sha256))

    def close(self):
        if self.stream is not None:self.stream.close();self.stream=None
        if not self.lock.closed:fcntl.flock(self.lock,fcntl.LOCK_UN);self.lock.close()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
