"""Last two developments under existing caps; no numerical cap extension."""
from .resources import P,G,MODULE,read,write,sha,service_totals
from .resources import authority as prior_authority


def authority():
    plan=prior_authority()
    scope=read(G/'FINAL_TWO_SCOPE.json')
    auth=read(G/'FINAL_TWO_AUTHORIZATION.json')
    assert auth['authorized'] is True and auth['scope_sha256']==sha(G/'FINAL_TWO_SCOPE.json')
    assert scope['max_additional_developments']==2 and scope['starting_task_attempts']==34
    assert scope['task_attempt_stop']==36 and scope['hard_caps_unchanged'] is True
    assert scope['holdouts_enabled'] is False and scope['production_enabled'] is False
    assert plan['experiment_limits']['max_task_physics_steps']==500000
    assert plan['experiment_limits']['max_diagnostic_physics_steps']==2000
    assert plan['resources']['max_new_disk_bytes']==13*1024**3//4
    return plan


def charge(**delta):
    limits=authority()['experiment_limits'];counters=read(P/'COUNTERS.json')
    for key,value in delta.items():
        assert type(value) is int and value>=0
        assert key in counters and counters[key]+value<=limits['max_'+key],key
        if key=='task_attempts':assert counters[key]+value<=36,'final_two_exhausted'
        counters[key]+=value
    write(P/'COUNTERS.json',counters)
