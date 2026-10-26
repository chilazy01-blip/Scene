import argparse,hashlib,json
from pathlib import Path
import numpy as np
import mujoco
from .control import ClosureContract,ClosureController,observation
from .verification import checks,consume_baseline,book_frame_regression
from sage.experiments.embodied_grasp_validation_v1.native import Stretch
from sage.experiments.embodied_grasp_validation_v1.build import write


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['check']);parser.add_argument('stage',type=Path)
    args=parser.parse_args(argv);r=args.stage.resolve();frozen=json.loads((r/'protocol/SOFTWARE_FREEZE.json').read_text())['files']
    for p,h in frozen.items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
    p=json.loads((r/'protocol/PROTOCOL.json').read_text());source=Path(p['source_stage']);control=json.loads((r/'protocol/CONTROL.json').read_text())
    assert hashlib.sha256((r/'evidence/TIMELINE.json').read_bytes()).hexdigest()==control['source_timeline_sha256']
    baseline=json.loads((source/'protocol/PROTOCOL.json').read_text());binding=json.loads(Path(baseline['source_binding']).read_text());timelines=json.loads((r/'evidence/TIMELINE.json').read_text());result=[]
    for cid,values in control['contracts'].items():
        contract=ClosureContract(**values);software=checks(contract);assert software['passed']
        consumer=consume_baseline(source,cid,contract)
        out=source/'combinations'/cid;task=json.loads((out/'TASK.json').read_text());m=mujoco.MjModel.from_xml_path(task['model']);d=mujoco.MjData(m);native=Stretch(m,binding)
        assert m.actuator_gainprm[5,0]==contract.kp and m.actuator_biasprm[5,2]==-contract.kd
        timeline=next(x for x in timelines if x['id']==cid);event=timeline['events']['first_load_capable_pad_quality'];index=event['step']
        with np.load(out/'close/RAW.npz') as z:
            d.qpos[:]=z['qpos'][index];d.qvel[:]=z['qvel'][index];command=z['ctrl'][index-1].copy()
        mujoco.mj_forward(m,d)
        obs=dict(time=0.,position=float(d.actuator_length[5]),velocity=float(d.actuator_velocity[5]),native_force=0.,left_force=event['left_force_N'],right_force=event['right_force_N'],left_pad_fraction=event['left_pad_fraction'],right_pad_fraction=event['right_pad_fraction'],com_offset=.02,passive_speed=event['passive_max_rad_s'])
        output=ClosureController(contract).update(command[5],obs);assert output['state']=='confirming'
        command[5]=output['command'];native.command(d,command);mujoco.mj_forward(m,d)
        error=abs(float(d.actuator_force[5])-output['predicted_native_force']);assert error<1e-9 and d.time==0
        before=d.ctrl.copy()
        try:native.command(d,command,units='degrees')
        except ValueError:unit_rejected=bool(np.array_equal(d.ctrl,before))
        else:unit_rejected=False
        assert unit_rejected
        result.append(dict(id=cid,software=software,saved_consumer=consumer,native_entry=dict(passed=True,force_prediction_max_error_N=error,invalid_units_rejected_before_write=unit_rejected,new_physics_steps=0)))
    frame=book_frame_regression(p['book_stage']);write(r/'evidence/BOOK_FRAME_REGRESSION.json',frame)
    write(r/'evidence/SOFTWARE_RESULT.json',dict(status='pass',combinations=result,book_frame_regression=frame['passed'],new_physics_steps=0,
          dynamics_admission='eligible for separately frozen bounded intervention; success unknown'))
    for path,h in frozen.items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==h,path
    print(json.dumps(dict(status='pass',combinations=result,book_frame_correct=True,new_physics_steps=0)),flush=True)


if __name__=='__main__':main()
