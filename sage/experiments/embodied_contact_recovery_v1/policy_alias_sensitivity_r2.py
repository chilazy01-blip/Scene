"""Static ONNX input crossover for legacy body-policy slots; no dynamic rollout."""
import numpy as np,h5py,mujoco,onnxruntime as ort
from .work import E,R,c,finish
folder=E/'jobs/C_development_03/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));cfg=c.read(R/'branches/A/source/model_config.json');names=cfg['joint_names'];default=np.array([cfg['default_joint_pos'].get(n,0.) for n in names])
si=[i for i,n in enumerate(names) if n.startswith('right_') and any(j in n for j in ['shoulder','elbow','wrist'])];assert len(si)==7
options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
session=ort.InferenceSession(str(R/'branches/A/source/walker.onnx'),options,providers=['CPUExecutionProvider']);input_name=session.get_inputs()[0].name;rows=[];calls=0
with h5py.File(folder/'TRACE.h5','r') as f:
 p=f['policy/walker_onnx'];pr=p['physics_row'][:];key=next(iter(p['input']));oldoutput=next(iter(p['output']))
 contacts=f['contacts/rows'][:];bad=int(contacts[contacts[:,3]<-.01][0,0])
 targets=sorted(set([0,800,4000,max(0,bad-160),max(0,bad-80),bad,bad+80,6872,6880,6904,8000,16000,24000,28000]))
 for k in targets:
  idx=int(np.searchsorted(pr,k,side='right')-1);raw=p['input'][key][idx];modified=raw.copy();flat=modified.reshape(-1)
  for i in si:flat[9+i]=-default[i];flat[38+i]=0.
  actual=session.run(None,{input_name:raw})[0];calls+=1;counter=session.run(None,{input_name:modified})[0];calls+=1
  expected=p['output'][oldoutput][idx];assert np.array_equal(actual,expected)
  delta=counter.reshape(-1)-actual.reshape(-1);scales=np.array([cfg['action_scales'][n] for n in names])
  rows.append({'physics_row':int(pr[idx]),'time':float(f['substep/time_before'][int(pr[idx])]),'legacy_right_slots_position':raw.reshape(-1)[[9+i for i in si]].tolist(),'legacy_right_slots_velocity':raw.reshape(-1)[[38+i for i in si]].tolist(),'counterfactual_position':flat[[9+i for i in si]].tolist(),'raw_recompute_max_error':0.,'leg_target_max_difference_rad':float(np.max(abs(delta[:12]*scales[:12]))),'leg_target_differences_rad':(delta[:12]*scales[:12]).tolist(),'velocity_command':raw.reshape(-1)[-3:].tolist()})
report={'physics_steps':0,'wbc_forwards':calls,'source':str(folder),'source_body_policy_deliberately_uses_zero_left_finger_alias_for_right_arm_slots':True,'counterfactual':'Hold those seven legacy slots at source-training zero physical finger angle/velocity; do not feed true right-arm pose (source evidence rejects that).','rows':rows,'dynamic_admission':False,'production_accepted':False}
c.write(E/'C3_POLICY_ALIAS_SENSITIVITY.json',report);finish(report,{'wbc_forwards':calls})
