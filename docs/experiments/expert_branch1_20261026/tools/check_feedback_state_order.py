"""Cross-check compact actual hand positions against the independent native schema."""
from pathlib import Path
import sys
from sage.experiments.embodied_expert_branch1_v1.common import ROOT,read_bound_json,safe_save,_file_binding
name=sys.argv[1];t=ROOT/'trials'/name;packet=read_bound_json(t/'PHASE_FEEDBACK_V3.json');schema=read_bound_json(ROOT/'ROBOT_DATA_SCHEMA_BASELINE.json')
indices=[x['joint_qpos_address'] for x in schema['hand_target_order']];names=[x['joint_name'] for x in schema['hand_target_order']]
assert indices==packet['state_order']['hand_qpos_indices'] and names==packet['state_order']['hand_names']
assert indices!=list(range(36,50))
r=read_bound_json(t/'full/REPORT.json');trace=read_bound_json(Path(r['trace']['path']));rows=trace['warmup_substeps']+[s for row in trace['records'] for s in row['substeps']]
for entry in packet['timeline']:
 s=rows[entry['physics_index']]
 assert entry['actual_finger_qpos_rad']==[s['full_qpos_after'][i] for i in indices]
 assert entry['hand_target_rad']==s['hand_target_rad']
 assert entry['actual_finger_actuator_force_nm']==s['actual_finger_actuator_force_nm']
safe_save(t/'FEEDBACK_STATE_ORDER_CHECK.json',dict(passed=True,new_physics_steps=0,timeline_samples=len(packet['timeline']),native_qpos_indices=indices,names=names,feedback=_file_binding(t/'PHASE_FEEDBACK_V3.json'),schema=_file_binding(ROOT/'ROBOT_DATA_SCHEMA_BASELINE.json'),trace=r['trace'],implementation=_file_binding(Path(__file__))))
print('actual compact hand state matches independent schema and raw trace',name,len(packet['timeline']))
