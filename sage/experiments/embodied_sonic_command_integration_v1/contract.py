"""Read executable interface contracts from the pinned official source tree."""
from __future__ import annotations
import ast
from dataclasses import dataclass
from pathlib import Path
import re
import json
import subprocess
import numpy as np

DEFAULT_SOURCE = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_data_stability_sonic_readmission_20261018_v1/source')

def finite(value, shape, name, dtype=np.float64):
    a=np.array(value,dtype=dtype,copy=True)
    if a.shape!=shape or not np.isfinite(a).all():raise ValueError(f'{name} must be finite {shape}, got {a.shape}')
    a.setflags(write=False)
    return a

def reorder(values,source_names,target_names):
    source_names=tuple(source_names);target_names=tuple(target_names)
    if len(set(source_names))!=len(source_names) or len(set(target_names))!=len(target_names):raise ValueError('duplicate joint names')
    if set(source_names)!=set(target_names):raise ValueError('joint name sets differ')
    a=finite(values,(len(source_names),),'joint values')
    return np.array([a[source_names.index(n)] for n in target_names])

@dataclass(frozen=True)
class OfficialContract:
    source: Path
    header_size: int
    body_names: tuple[str,...]
    left_names: tuple[str,...]
    right_names: tuple[str,...]
    state_names: tuple[str,...]
    groups: dict[str,tuple[str,...]]
    source_files: tuple[Path,...]

    @property
    def hand_names(self):return self.left_names+self.right_names

def load_contract(source=DEFAULT_SOURCE):
    source=Path(source);base=source/'gear_sonic_deploy/src/g1/g1_deploy_onnx_ref'
    sender=source/'gear_sonic/utils/teleop/zmq/zmq_planner_sender.py'
    receiver=base/'include/input_interface/zmq_packed_message_subscriber.hpp'
    supplemental=source/'gear_sonic/data/robot_model/supplemental_info/g1/g1_supplemental_info.py'
    urdf=source/'gear_sonic/data/robot_model/model_data/g1/g1_29dof_with_hand.urdf'
    vals={}
    for node in ast.walk(ast.parse(supplemental.read_text())):
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in ('body_actuated_joints','left_hand_actuated_joints','right_hand_actuated_joints','joint_groups'):vals[target.id]=ast.literal_eval(node.value)
    a=int(re.search(r'^HEADER_SIZE\s*=\s*(\d+)',sender.read_text(),re.M)[1]);b=int(re.search(r'HEADER_SIZE\s*=\s*(\d+)',receiver.read_text())[1])
    if a!=b:raise ValueError(f'official sender/receiver header mismatch: {a}/{b}')
    # The cached Pinocchio binary is built against NumPy1. Keep it isolated
    # from the simulation's NumPy2 process rather than importing a crashing ABI.
    pin_python=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_g1_runtime_20260926_v1/prefix/bin/python')
    code='import pinocchio as p,json,sys; m=p.buildModelFromUrdf(sys.argv[1]); print(json.dumps([n for i,n in sorted((m.joints[m.getJointId(n)].idx_q,str(n)) for n in m.names[1:])]))'
    result=subprocess.run([str(pin_python),'-I','-c',code,str(urdf)],capture_output=True,text=True,check=True,timeout=30)
    state_names=tuple(json.loads(result.stdout))
    groups={g:tuple(sorted(vals['joint_groups'][g]['joints'],key=state_names.index)) for g in ('left_leg','right_leg','waist','left_arm','right_arm','left_hand','right_hand')}
    body=tuple(vals['body_actuated_joints']);left=tuple(vals['left_hand_actuated_joints']);right=tuple(vals['right_hand_actuated_joints'])
    if len(body)!=29 or len(left)!=7 or len(right)!=7 or set(state_names)!=set(body+left+right):raise ValueError('official 29+7+7 contract differs')
    return OfficialContract(source,a,body,left,right,state_names,groups,(sender,receiver,supplemental,urdf,base/'include/dex3_hands.hpp',source/'gear_sonic/scripts/run_vla_inference.py'))
