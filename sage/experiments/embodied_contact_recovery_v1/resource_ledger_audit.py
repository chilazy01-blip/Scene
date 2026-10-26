"""Recompute ledger totals from preserved receipts and explicit credits."""
import math
import sys
from pathlib import Path
from .work import E, c, finish


def main(config):
    cfg = c.read(config)
    state, plan = c.read(cfg['state_snapshot']), c.read(cfg['plan_snapshot'])
    definitions = {**plan['jobs'], **state.get('additional_jobs',{})}
    keys = list(plan['limits'])
    totals = dict(plan['initial_spent'])
    pools = {pool:{k:0 for k in keys} for pool in plan['protected_pools']}
    credits, modes, counted = [], {}, []
    mismatches = []
    for name, entry in state['jobs'].items():
        if 'usage' not in entry:continue
        definition = definitions[name]
        usage = entry['usage']
        for key in keys:
            value = usage.get(key,0)
            if value < 0 or not math.isfinite(value) or value > definition['reservation'].get(key,0)+1e-8:
                mismatches.append({'job':name,'resource':key,'error':'usage_outside_reservation','value':value})
            totals[key] += value
            if definition['pool'] in pools:pools[definition['pool']][key] += value
        folder = E/'jobs'/name
        request = folder/'REQUEST.json'
        accounting = entry.get('evidence',{}).get('accounting','pre_dispatch_or_legacy')
        modes[accounting] = modes.get(accounting,0)+1
        if request.exists():
            if c.read(request) != definition:mismatches.append({'job':name,'error':'request_differs_from_definition'})
            if accounting == 'request_bound_actual_usage':
                final = c.read(folder/'USAGE_FINAL.json')
                if not final['complete'] or final['request_sha256'] != c.sha(request):
                    mismatches.append({'job':name,'error':'invalid_completed_usage_binding'})
                for key in keys:
                    if key != 'service_seconds' and usage.get(key,0) != final['usage'].get(key,0):
                        mismatches.append({'job':name,'resource':key,'error':'actual_usage_receipt_mismatch'})
        counted.append(name)
    seen = set()
    for event in state['events']:
        if 'credit' not in event:continue
        assert event['action'] == 'reconcile_completed_zero_integration_receipt'
        name=event['job'];assert name not in seen;seen.add(name)
        assert state['jobs'][name]['reconciliation'] == event
        assert all(c.sha(path) == digest for path,digest in event['basis'].items())
        result=c.read(E/'jobs'/name/'RESULT.json')
        assert result.get('trace_summary',result.get('summary',{})).get('physics_steps') == 0
        assert event['original_receipt_preserved'] and event['elapsed_service_and_historical_failures_retained']
        assert event['credit'].get('service_seconds',0) == 0
        for key,value in event['credit'].items():
            assert 0 <= value <= state['jobs'][name]['usage'].get(key,0)
            totals[key] -= value
        credits.append(event)
    differences={k:totals[k]-state['spent'][k] for k in keys}
    for key,delta in differences.items():
        if abs(delta)>1e-7:mismatches.append({'resource':key,'error':'aggregate_mismatch','difference':delta})
    for pool,usage in pools.items():
        for key,value in usage.items():
            if abs(value-state['pool_spent'][pool].get(key,0))>1e-7:
                mismatches.append({'pool':pool,'resource':key,'error':'protected_pool_mismatch'})
    clock=c.read(E/'RUN_CLOCK.json')
    assert clock == plan['clock']
    assert plan['limits']['task_attempts']-plan['initial_spent']['task_attempts'] == 18
    assert abs(plan['limits']['service_seconds']-plan['initial_spent']['service_seconds']-48000)<1e-7
    assert plan['limits']['task_physics_steps']+plan['limits']['diagnostic_physics_steps'] == 4770866
    assert all(state['spent'][k] <= plan['limits'][k] for k in keys)
    remaining={k:plan['limits'][k]-state['spent'][k] for k in keys}
    protected_unspent={k:sum(max(0,pool.get(k,0)-state['pool_spent'][name].get(k,0)) for name,pool in plan['protected_pools'].items()) for k in keys}
    report={'passed':not mismatches,'mismatches':mismatches,'completed_jobs_reconciled':len(counted),
        'receipt_accounting_modes':modes,'explicit_credits':credits,'recomputed_spent':totals,
        'state_spent_minus_initial':{k:state['spent'][k]-plan['initial_spent'][k] for k in keys},
        'aggregate_roundoff_differences':differences,'limits':plan['limits'],'remaining':remaining,
        'protected_pool_usage':pools,'unspent_protected_reservations':protected_unspent,
        'unprotected_remaining':{k:remaining[k]-protected_unspent[k] for k in keys},
        'clock_unchanged':True,'clock':clock,'new_task_cap':18,'new_service_seconds_cap':48000,
        'diagnostic_transfer_preserves_combined_physics_cap':True,'state_snapshot_sha256':c.sha(cfg['state_snapshot']),
        'plan_snapshot_sha256':c.sha(cfg['plan_snapshot']),'active_at_snapshot':state['active'],
        'this_audit_service_is_charged_after_snapshot':True,'new_physics_steps':0,'new_render_passes':0,
        'whole_run_closure_claim':False}
    c.write(E/cfg['output'],report)
    assert report['passed'],mismatches[:10]
    finish(report)


if __name__ == '__main__':main(sys.argv[1])
