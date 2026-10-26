"""The actual ONNX decoder and native29+14 PD seam, without any physics stepping."""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from .contract import finite
from .commands import CommandFrame,FrameLatch,ActionChunk
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import ENCODER_ASSEMBLER,ENCODER_DIMENSION,DECODER_DIMENSION,body_joint_target_from_raw_action
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import _make_session
from sage.experiments.embodied_native_sonic_transport_v1.rate_adapter import project_target
from sage.experiments.embodied_native_sonic_transport_v1.effort_adapter import native_torque
from sage.experiments.embodied_native_sonic_transport_v1.control import feedforward
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native

@dataclass(frozen=True)
class DecodedCommand:
    frame: CommandFrame
    raw_body: np.ndarray
    body_target: np.ndarray
    hand_target: np.ndarray

def validate_hand_transition(previous,current,stage):
    old=finite(previous,(14,),'previous hand reference')
    new=finite(current,(14,),'current hand reference')
    # .006 is the original gripping-feedback rule. Original deliberate release
    # uses a 60-tick smooth curve and must not be replaced with this rate rule.
    if stage not in ('release','retract','settle','done') and np.max(np.abs(new-old))>.006+1e-12:
        raise ValueError('hand reference exceeds original gripping .006rad/tick limit')

class SonicRuntime:
    def __init__(self,contract,decoder,encoder=None):
        self.contract=contract;self.decoder=decoder;self.encoder=encoder;self.latch=FrameLatch()
    @classmethod
    def from_paths(cls,contract,decoder_path,encoder_path=None):
        return cls(contract,_make_session(Path(decoder_path)),_make_session(Path(encoder_path)) if encoder_path is not None else None)
    def encode(self,blocks):
        if self.encoder is None:raise ValueError('encoder model not configured')
        a=ENCODER_ASSEMBLER.assemble(blocks) if isinstance(blocks,dict) else blocks
        a=finite(a,(ENCODER_DIMENSION,),'encoder input',np.float32)[None]
        return np.asarray(self.encoder.run(None,{self.encoder.get_inputs()[0].name:a})[0],dtype=np.float32).reshape(64)
    def decode(self,frame,decoder_input,native_hand_names,now_s):
        a=finite(decoder_input,(DECODER_DIMENSION,),'decoder input',np.float32).copy();a[:64]=frame.token
        raw=np.asarray(self.decoder.run(None,{self.decoder.get_inputs()[0].name:a[None]})[0],dtype=np.float32).reshape(29)
        raw=finite(raw,(29,),'decoded body action',np.float32)
        target=np.asarray(body_joint_target_from_raw_action(raw,phase='native_mug_transport',sim_time_s=now_s).position_target_rad)
        hands=frame.native_hands(self.contract,native_hand_names)
        self.latch.accept(frame,now_s)
        return DecodedCommand(frame,raw,target,hands)
    def task_frame(self,task,tick,data,initial_quat,native_hand_names):
        token=self.encode(task.reference_blocks(tick,data,initial_quat))
        return CommandFrame.from_task(self.contract,token,native_hand_names,task.hand_targets(native_hand_names),frame_index=int(tick),observation_time_s=float(data.time),source='task_expert/'+type(task).__module__)

class NativeDriver:
    """Apply original range/rate/effort and PD rules to all43 existing motors."""
    def __init__(self,mj,model,hand_reference_bounds=None):
        self.model=model;self.ids=native._model_ids(mj,model);self.hand=hand_ids(model);self.control={k:np.asarray(v) for k,v in native.official_control_arrays().items()};self.bounds=hand_reference_bounds
        motors=list(self.ids['actuator_ids'])+list(self.hand['actuators'])
        if model.nu!=43 or len(set(motors))!=43:raise ValueError('requires all43 unique original actuators')
    def body_target(self,decoded,previous):
        lo,hi=self.model.jnt_range[self.ids['joint_ids']].T
        return project_target(decoded.body_target,previous,lo,hi,native.MAX_CANDIDATE_STEP_RAD,True)
    def torques(self,data,body_target,hand_target,active=True):
        ids=self.ids;h=self.hand;m=self.model
        target=finite(hand_target,(14,),'native hand target')
        limits=m.jnt_range[[m.joint(n).id for n in h['names']]]
        if self.bounds is not None:
            bounds=finite(self.bounds,(14,2),'hand reference bounds')
            limits=np.column_stack((np.maximum(limits[:,0],bounds[:,0]),np.minimum(limits[:,1],bounds[:,1])))
        if np.any(limits[:,0]>limits[:,1]):raise ValueError('empty native/case range intersection')
        if limits.shape!=(14,2) or np.any(target<limits[:,0]-1e-12) or np.any(target>limits[:,1]+1e-12):raise ValueError('hand reference exceeds native/case bounds')
        body_target=finite(body_target,(29,),'body target');body=self.control['kp']*(body_target-data.qpos[ids['qpos_ids']])-self.control['kd']*data.qvel[ids['dof_ids']]+feedforward(data.qfrc_bias[ids['dof_ids']],active)
        fingers=h['kp']*(target-data.qpos[h['qpos']])-h['kd']*data.qvel[h['dofs']]
        output=np.zeros(m.nu);output[ids['actuator_ids']]=native_torque(body,self.control['effort_limit'],m.actuator_ctrlrange[ids['actuator_ids']]);output[h['actuators']]=np.clip(fingers,m.actuator_ctrlrange[h['actuators'],0],m.actuator_ctrlrange[h['actuators'],1])
        return output,body,fingers

class Gr00tSource:
    """Official PolicyClient seam; no substitute policy when service is absent."""
    def __init__(self,client):self.client=client;self.chunk=None
    @classmethod
    def connect(cls,host,port):
        if not host:raise ValueError('explicit GR00T policy endpoint required')
        try:from gr00t.policy.server_client import PolicyClient
        except ImportError as exc:raise RuntimeError('Isaac-GR00T PolicyClient is unavailable; no GR00T model is connected') from exc
        client=PolicyClient(host=host,port=port)
        if not client.ping():raise RuntimeError('GR00T policy service is unreachable')
        return cls(client)
    def infer(self,observation,observation_time_s):
        action,_info=self.client.get_action(observation);chunk=ActionChunk.from_policy(action,observation_time_s);self.chunk=chunk;return chunk
    def frame(self,now_s,frame_index):
        if self.chunk is None:raise RuntimeError('no GR00T action chunk has been received')
        return self.chunk.sample(now_s,frame_index)
