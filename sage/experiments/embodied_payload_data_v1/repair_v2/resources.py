"""Versioned authority and cumulative accounting; never reset old counters."""
from pathlib import Path
import hashlib
import json
import os
import time

P = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/payload_data_20261009')
MODULE = Path(__file__).resolve().parents[1]
read = lambda p: json.loads(Path(p).read_text())
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def authority():
    plan = read(P/'PLAN.json')
    assert read(P/'AUTHORIZATION.json')['plan_sha256'] == sha(P/'PLAN.json')
    extension = read(P/'repair_v2/RESOURCE_AUTHORIZATION.json')
    proposal = read(P/'repair_v2/RESOURCE_PROPOSAL.json')
    assert extension['approved'] is True
    assert extension['proposal_sha256'] == sha(P/'repair_v2/RESOURCE_PROPOSAL.json')
    assert extension['other_caps_unchanged'] is True and extension['counters_reset'] is False
    assert extension['approved_task_attempt_cap'] == proposal['requested_attempts_cap'] == 37
    plan['experiment_limits']['max_task_attempts'] = 37
    storage = read(P/'ADDITIONAL_STORAGE_PROPOSAL_r1.json')
    auth = read(P/'ADDITIONAL_STORAGE_AUTHORIZATION_r1.json')
    assert auth['approved'] is True and auth['proposal_sha256'] == sha(P/'ADDITIONAL_STORAGE_PROPOSAL_r1.json')
    plan['resources']['max_new_disk_bytes'] = storage['requested_stage_cap_bytes']
    return plan


def write(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    tmp.replace(path)


def charge(**delta):
    # Launcher holds the same persistent execution lock throughout the service.
    limits = authority()['experiment_limits']
    counters = read(P/'COUNTERS.json')
    for key, value in delta.items():
        assert isinstance(value, int) and value >= 0
        assert key in counters and counters[key]+value <= limits['max_'+key], key
        counters[key] += value
    write(P/'COUNTERS.json', counters)


def receipt_paths(root, prefix=''):
    paths = []
    for entry in os.scandir(Path(root)/'services'):
        if entry.name.startswith(prefix) and entry.is_dir(follow_symlinks=False):
            receipt = Path(entry.path)/'supervisor.json'
            if receipt.is_file():
                paths.append(receipt)
            elif prefix == 'fbts_payloaddata_':
                raise RuntimeError('unreconciled_service:'+entry.path)
    return paths


def service_totals(shared_roots):
    n = P.parents[1]
    r = n.parents[1]
    baseline = read(P/'BASELINE_LEDGER.json')
    reserve = read(P.parent/'native_source_20261008/BASELINE_LEDGER.json')['prior_audit_conservative_reserve_seconds']
    receipts = {}
    for root in shared_roots:
        for path in receipt_paths(root):
            receipts[str(path)] = read(path)
    stage = [v for k,v in receipts.items() if Path(k).parent.parent == r/'services' and Path(k).parent.name.startswith('fbts_payloaddata_')]
    cost = sum(v['elapsed_seconds'] for v in stage)
    common = sum(v.get('elapsed_seconds',0) for k,v in receipts.items() if Path(k).parent.parent == r/'services' and Path(k).parent.name.startswith('fbts_'))+reserve
    total = sum(v.get('elapsed_seconds',0) for v in receipts.values())+reserve
    return dict(stage_service_seconds=cost,
                package_service_seconds=max(common, baseline['package_service_seconds']+cost),
                global_service_seconds=max(total, baseline['global_service_seconds']+cost),
                service_receipts=len(stage), all_receipts=len(receipts))
