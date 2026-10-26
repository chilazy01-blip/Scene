"""Correct preflight false positives: the original supported mug stays on the desk."""
import argparse
from pathlib import Path
from .report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root):
    src=root/'TUCK_PREFLIGHT_V5.json'; original=read_bound_json(src)
    for a in original['attempts']:
        for s in a['samples']:
            s['bad']=[c for c in s['bad'] if sorted(x['body'] for x in c['pair']) != ['generated_desk','payload']]
        a['passed']=all(not s['bad'] and s['penetration_m']<=.01 for s in a['samples'])
        print(dict(angles=a['angles_rad'],passed=a['passed'],bad_samples=sum(bool(s['bad']) for s in a['samples'])),flush=True)
    safe_save(root/'TUCK_PREFLIGHT_REVIEW_V5.json',dict(schema='native-tucked-corrected-clearance/v5',
        physics_steps=0, additional_fk_samples=0, original=_file_binding(src),implementation=_file_binding(Path(__file__)),
        correction='original preflight wrongly classified normal mug-desk support as forbidden scene contact; remove exactly that body pair, keep all robot contacts/depth and preserve original report',
        attempts=original['attempts']))
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
