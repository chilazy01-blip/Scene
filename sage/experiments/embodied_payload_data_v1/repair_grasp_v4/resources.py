"""The explicit40-attempt extension; all prior authority/cost stays cumulative."""
from ..repair_v2.resources import P, MODULE, read, write, sha, service_totals
from ..repair_v2.resources import authority as prior_authority

G=P/'repair_grasp_r1'


def authority():
    plan=prior_authority()
    auth=read(G/'RESOURCE_AUTHORIZATION.json')
    proposal=read(auth['proposal_path'])
    assert auth['approved'] is True and auth['proposal_sha256']==sha(auth['proposal_path'])
    assert auth['other_caps_unchanged'] is True and auth['counters_reset'] is False
    assert auth['approved_task_attempt_cap']==proposal['requested_change']['max_task_attempts']['requested']==40
    plan['experiment_limits']['max_task_attempts']=40
    return plan


def charge(**delta):
    limits=authority()['experiment_limits'];counters=read(P/'COUNTERS.json')
    for key,value in delta.items():
        assert type(value) is int and value>=0
        assert key in counters and counters[key]+value<=limits['max_'+key],key
        counters[key]+=value
    write(P/'COUNTERS.json',counters)
