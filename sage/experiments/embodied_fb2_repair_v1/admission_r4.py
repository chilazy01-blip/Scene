"""Future admission must resolve integrated coordination and collision findings."""
import hashlib,json
from pathlib import Path
from .admission_r3 import require_full_task as require_previous

REQUIRED_INTEGRATION={'task_progress_after_stop','prospective_resume_collision_coverage',
                      'native_collision_depth_fidelity','history_dependent_integrated_acceptance'}


def require_full_task(recheck_path):
    findings=json.loads(Path(recheck_path).read_text());issues={x['id']:x for x in findings['findings']}
    unresolved=[x for x in sorted(REQUIRED_INTEGRATION) if x not in issues or issues[x]['status']!='validated']
    if unresolved:raise RuntimeError('unresolved_integrated_findings:'+','.join(unresolved))
    for key in REQUIRED_INTEGRATION:
        if not issues[key].get('evidence'):raise RuntimeError('missing_integrated_evidence:'+key)
        for item in issues[key]['evidence']:
            if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()!=item['sha256']:raise RuntimeError('integrated_evidence_changed:'+key)
    return require_previous(recheck_path)
