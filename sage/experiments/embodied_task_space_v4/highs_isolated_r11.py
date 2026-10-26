"""Load the isolated, hash-bound HiGHS runtime without changing shared scipy."""
from pathlib import Path
import hashlib,json,sys
root=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4')
ready=json.loads((root/'dependencies/HIGHSPY_READY.json').read_text())
assert ready['passed'] and ready['version']=='1.15.1'
for p,h in ready['files'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
sys.path.insert(0,str(root/'dependencies/highspy_1_15_1'))
import highspy as hc
assert hc.Highs().version()=='1.15.1'
