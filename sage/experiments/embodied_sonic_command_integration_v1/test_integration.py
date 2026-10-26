"""Contract tests use pinned official executable functions as the wire oracle."""
import ast
import importlib.util
import json
import numpy as np
import pytest
from .contract import load_contract,reorder
from .commands import CommandFrame,ActionChunk,FrameLatch
from .wire import pack,unpack
from .observation import build_observation

@pytest.fixture(scope='module')
def contract():return load_contract()

def frame(contract,**kw):
    args=dict(token=np.linspace(-1,1,64),left=np.arange(7)/100,right=-np.arange(7)/50,frame_index=12,observation_time_s=2.,source='fixture')
    args.update(kw);return CommandFrame(**args)

def official_functions(contract):
    path=contract.source_files[0]
    spec=importlib.util.spec_from_file_location('pinned_sender',path);sender=importlib.util.module_from_spec(spec);spec.loader.exec_module(sender)
    tree=ast.parse(contract.source_files[-1].read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='pack_latent_action_message')
    scope=dict(np=np,pack_pose_message=sender.pack_pose_message)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(contract.source_files[-1]),'exec'),scope)
    return sender,scope['pack_latent_action_message']

def test_official_byte_identity(contract):
    f=frame(contract);sender,official=official_functions(contract)
    assert contract.header_size==sender.HEADER_SIZE==1280
    assert pack(f,contract)==official(f.token,np.array([f.frame_index]),f.left,f.right)
    restored=unpack(pack(f,contract),contract,observation_time_s=2.)
    assert np.array_equal(restored.token,f.token)
    assert np.array_equal(restored.left,f.left.astype(np.float32))

def test_named_index_middle_mapping(contract):
    # Physical joint order deliberately differs and all index/middle values differ.
    order=tuple(n for side in ('left','right') for digit in ('thumb','middle','index') for n in contract.hand_names if n.startswith(side+'_hand_'+digit))
    values=np.arange(14,dtype=float)/100
    f=CommandFrame.from_task(contract,np.zeros(64),order,values,frame_index=0,observation_time_s=0.,source='fixture')
    for names,a in ((contract.left_names,f.left),(contract.right_names,f.right)):
        assert all(a[i]==values[order.index(n)] for i,n in enumerate(names))
    assert np.array_equal(f.native_hands(contract,order),values)
    assert contract.left_names[3].startswith('left_hand_index')
    assert contract.groups['left_hand'][0].startswith('left_hand_index')
    assert contract.groups['left_hand'][4].startswith('left_hand_thumb')

@pytest.mark.parametrize('bad', ['missing','duplicate','nonfinite'])
def test_bad_joint_maps(contract,bad):
    names=list(contract.hand_names);a=np.zeros(14)
    if bad=='missing':names[-1]='unknown'
    elif bad=='duplicate':names[-1]=names[0]
    else:a[-1]=np.nan
    with pytest.raises(ValueError):reorder(a,names,contract.hand_names)

@pytest.mark.parametrize('bad',['truncated','trailing','old_header','missing_hand','nan','bad_version'])
def test_reject_bad_wire(contract,bad):
    f=frame(contract);message=pack(f,contract)
    if bad=='truncated':message=message[:-1]
    elif bad=='trailing':message+=b'\0'
    elif bad=='old_header':message=message[:1028]+message[1284:]
    elif bad=='nan':
        message=message[:1284]+np.array([np.nan],dtype='<f4').tobytes()+message[1288:]
    else:
        sender,_=official_functions(contract)
        if bad=='missing_hand':message=sender.pack_pose_message({'token_state':f.token.reshape(1,64),'frame_index':np.array([12],dtype=np.int64)},version=4)
        else:
            head=json.loads(message[4:1284].split(b'\0')[0]);head['v']=3
            message=b'pose'+json.dumps(head).encode().ljust(1280,b'\0')+message[1284:]
    with pytest.raises(ValueError):unpack(message,contract,observation_time_s=2.)

def policy_action():return {'action.motion_token':np.zeros((1,40,64)),'action.left_hand_joints':np.ones((1,40,7))*.01,'action.right_hand_joints':np.ones((1,40,7))*.02}

def test_chunk_latency_and_expiry():
    action=policy_action();action['action.motion_token'][0,:,0]=np.arange(40)/40
    chunk=ActionChunk.from_policy(action,10.)
    assert chunk.sample(10.2,4).token[0]==np.float32(.25)
    with pytest.raises(ValueError):chunk.sample(10.8,5)
    with pytest.raises(ValueError):chunk.sample(9.,6)

@pytest.mark.parametrize('bad',['ambiguous','missing','horizon','bound'])
def test_chunk_rejects_incomplete_action(bad):
    action=policy_action()
    if bad=='ambiguous':action['motion_token']=action['action.motion_token']
    elif bad=='missing':del action['action.right_hand_joints']
    elif bad=='horizon':action['action.left_hand_joints']=np.zeros((1,39,7))
    else:action['action.motion_token'][0,0,0]=2.
    with pytest.raises(ValueError):ActionChunk.from_policy(action,0.)

def test_invalid_frame_keeps_last_grip(contract):
    latch=FrameLatch();f=frame(contract);latch.accept(f,2.)
    for bad,now in [(f,2.),(frame(contract,frame_index=13),2.3),(frame(contract,frame_index=14,observation_time_s=3.),2.)]:
        with pytest.raises(ValueError):latch.accept(bad,now)
        assert latch.current is f
    with pytest.raises(ValueError):f.right[0]=9.

def observation(contract,**changes):
    args=dict(joint_names=contract.body_names+contract.hand_names,joint_positions=np.arange(43)/100,base_quat_wxyz=[1,0,0,0],images={'ego_view':np.zeros((8,10,3),np.uint8)},image_time_s=3.,state_time_s=3.,now_s=3.,prompt='fixture: move white mug',camera_calibrated=True)
    args.update(changes);return build_observation(contract,**args)

def test_observation_name_order_and_no_hardware_copy(contract):
    obs=observation(contract);names=contract.body_names+contract.hand_names
    for group,ordered in contract.groups.items():
        assert np.array_equal(obs['state'][group][0,0],np.array([names.index(n)/100 for n in ordered],np.float32))
    coupled=observation(contract,left_hardware_coupling=True)
    assert not np.array_equal(coupled['state']['left_hand'],obs['state']['left_hand'])
    assert np.array_equal(obs['state']['projected_gravity'],[[[0,0,-1]]])
    assert obs['video']['ego_view'].shape==(1,1,8,10,3)

def test_observation_against_official_function(contract):
    path=contract.source/'gear_sonic/utils/inference/vla_utils.py'
    node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='prepare_observation_for_eval')
    scope=dict(RobotModel=object)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),scope)
    class Robot:
        num_joints=43
        def get_joint_group_indices(self,name):return [contract.state_names.index(n) for n in contract.groups[name]]
    observed=observation(contract)
    expected=scope['prepare_observation_for_eval'](Robot(),{'q':observed['q'],'state':{}})
    for name in contract.groups:assert np.array_equal(observed['state'][name],expected['state'][name])

@pytest.mark.parametrize('changes',[{'camera_calibrated':False},{'image_time_s':2.},{'state_time_s':4.},{'images':{}},{'base_quat_wxyz':[0,0,0,0]}])
def test_observation_rejects_missing_or_stale_sensors(contract,changes):
    with pytest.raises(ValueError):observation(contract,**changes)

def test_grip_rate_preserves_original_release_curve():
    from .runtime import validate_hand_transition
    validate_hand_transition(np.zeros(14),np.ones(14)*.006,'close')
    with pytest.raises(ValueError):validate_hand_transition(np.zeros(14),np.ones(14)*.007,'carry')
    validate_hand_transition(np.ones(14)*.5,np.ones(14)*.485,'release')

@pytest.mark.parametrize('header',[[],{'v':4,'endian':'le','count':1,'fields':None},{'v':4,'endian':'le','count':1,'fields':[None]},{'v':4,'endian':'le','count':1,'fields':[{'name':[],'dtype':'f32','shape':None}]}])
def test_malformed_header_schema(contract,header):
    message=b'pose'+json.dumps(header).encode().ljust(1280,b'\0')
    with pytest.raises(ValueError):unpack(message,contract,observation_time_s=0.)

def test_policy_chunk_cannot_be_changed_after_receive():
    action=policy_action();chunk=ActionChunk.from_policy(action,0.)
    action['action.right_hand_joints'][:]=0.
    assert chunk.right[0,0]==np.float32(.02)
    with pytest.raises(ValueError):chunk.right[0,0]=0.
