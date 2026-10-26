"""Complete only missing metadata receipts for already finished native trials."""
import subprocess,sys
from sage.experiments.embodied_expert_branch1_v1.common import ROOT,read_bound_json
from sage.experiments.embodied_expert_branch1_v1.spatial_feedback import build
for t in sorted((ROOT/'trials').iterdir()):
 if not(t/'JOB.json').exists() or read_bound_json(t/'JOB.json')['status']!='complete':continue
 if not(t/'FEEDBACK_STATE_ORDER_CHECK.json').exists():
  subprocess.run([sys.executable,str(ROOT/'tools/check_feedback_state_order.py'),t.name],check=True)
 if not(t/'SPATIAL_FEEDBACK.json').exists():build(t)
 print(dict(trial=t.name,compact_feedback_complete=True,new_physics_steps=0),flush=True)
