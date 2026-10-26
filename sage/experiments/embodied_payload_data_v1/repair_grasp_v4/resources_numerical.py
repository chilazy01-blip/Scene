"""Prospective authority for finer integration; absent approval fails closed."""
from .resources import P,G,MODULE,read,write,sha,service_totals
from .resources import authority as prior_authority


def authority():
    plan=prior_authority();path=G/'NUMERICS_RESOURCE_AUTHORIZATION.json'
    if not path.is_file():raise RuntimeError('numerical_resource_extension_not_authorized')
    auth=read(path);proposal=read(G/'NUMERICS_RESOURCE_PROPOSAL_r1.json')
    assert auth['approved'] is True and auth['proposal_sha256']==sha(G/'NUMERICS_RESOURCE_PROPOSAL_r1.json')
    assert auth['counters_reset'] is False and auth['all_other_hard_caps_unchanged'] is True
    changes=proposal['requested_changes']
    assert auth['approved_changes']=={k:v['requested'] for k,v in changes.items()}
    assert changes['task_physics_steps']['requested']==700000
    assert changes['diagnostic_physics_steps']['requested']==3000
    assert changes['stage_disk_bytes']['requested']==4*1024**3
    assert changes['package_disk_bytes']['requested']==19*1024**3
    plan['experiment_limits']['max_task_physics_steps']=700000
    plan['experiment_limits']['max_diagnostic_physics_steps']=3000
    plan['resources']['max_new_disk_bytes']=4*1024**3
    return plan


def charge(**delta):
    limits=authority()['experiment_limits'];counters=read(P/'COUNTERS.json')
    for key,value in delta.items():
        assert type(value) is int and value>=0
        assert key in counters and counters[key]+value<=limits['max_'+key],key
        counters[key]+=value
    write(P/'COUNTERS.json',counters)
