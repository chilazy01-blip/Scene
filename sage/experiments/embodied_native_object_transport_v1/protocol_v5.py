"""Second and last version in the same new round, no geometry or gate relaxation."""
import argparse
from pathlib import Path
import time
from .protocol_v4 import authorize as parent, reserve as parent_reserve, project_target, check
from .report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def authorize(root):
    p=parent(root);v=read_bound_json(root/'VERSION_05_PROTOCOL.json')
    assert v['version']==5 and v['round_version_index']==2
    assert v['deadline_epoch_utc']==p['deadline_epoch_utc']
    for b in [v['parent'],v['cause_report'],v['cause_audit'],v['geometry'],*v['dependencies'].values()]:check(b)
    return p


def reserve(root,output,ceiling):
    authorize(root)
    assert output==root/'version_05/full'
    return parent_reserve(root,output,ceiling)


def freeze(root):
    p=parent(root);out=root/'VERSION_05_PROTOCOL.json'
    assert not out.exists() and time.time()<p['deadline_epoch_utc']
    pre=read_bound_json(root/'TUCK_ROUTE_PREFLIGHT_V5.json')
    assert pre['attempts'][2]['passed'] and pre['attempts'][2]['angles_rad']==[.75,-.25,0,1.2,0,0,0]
    safe_save(out,dict(schema='native-tucked-approach-revision/v5',version=5,round_version_index=2,
        parent=_file_binding(root/'PROTOCOL.json'),deadline_epoch_utc=p['deadline_epoch_utc'],
        cause_report=_file_binding(root/'version_04/full/REPORT.json'),cause_audit=_file_binding(root/'version_04/full/AUDIT.json'),
        geometry=_file_binding(root/'TUCK_ROUTE_PREFLIGHT_V5.json'),
        only_causal_change='initial100 ticks identical, 100tick two-segment tucked arm while standing, approach earliest225; original post-stop raise/grasp/task/control/projector/physical gates unchanged',
        limitation='zero-step FK screening does not qualify dynamics; source-stop raise still actual-state62point checked',
        budget='same round2h, max2causal versions and30000steps; no reset; this consumes final version',
        dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in ('task_v5.py','engine_v5.py','audit_v5.py','protocol_v5.py','tucked_route_preflight_v5.py','visualize_v5.py','closeout_v5.py','review_attempt_v5.py')}))
    print(dict(version=5,frozen=True,physics_steps=0),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
