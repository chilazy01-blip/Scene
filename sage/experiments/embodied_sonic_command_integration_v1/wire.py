"""Official protocol-v4 bytes, with explicit mandatory hand channels for this task."""
import json
import numpy as np
from .commands import CommandFrame

DTYPES={'f32':np.dtype('<f4'),'i64':np.dtype('<i8')}
SHAPES={'token_state':(1,64),'frame_index':(1,),'left_hand_joints':(1,7),'right_hand_joints':(1,7)}

def pack(frame,contract):
    arrays={'token_state':frame.token.reshape(1,64),'frame_index':np.array([frame.frame_index],dtype='<i8'),'left_hand_joints':frame.left.astype('<f4').reshape(1,7),'right_hand_joints':frame.right.astype('<f4').reshape(1,7)}
    fields=[dict(name=n,dtype='i64' if n=='frame_index' else 'f32',shape=list(a.shape)) for n,a in arrays.items()]
    header=json.dumps(dict(v=4,endian='le',count=1,fields=fields),separators=(',',':')).encode()
    if len(header)>contract.header_size:raise ValueError('header exceeds pinned contract')
    return b'pose'+header.ljust(contract.header_size,b'\0')+b''.join(a.tobytes() for a in arrays.values())

def unpack(message,contract,*,observation_time_s,source='zmq_v4'):
    size=contract.header_size
    if not isinstance(message,bytes) or not message.startswith(b'pose') or len(message)<4+size:raise ValueError('invalid pose message')
    raw=message[4:4+size];head,_,padding=raw.partition(b'\0')
    if padding.strip(b'\0'):raise ValueError('invalid header padding')
    try:header=json.loads(head)
    except (ValueError,UnicodeError) as exc:raise ValueError('invalid protocol header') from exc
    if not isinstance(header,dict) or not isinstance(header.get('fields'),list):raise ValueError('invalid protocol header schema')
    if (header.get('v'),header.get('endian'),header.get('count'))!=(4,'le',1):raise ValueError('requires protocol4 little-endian single frame')
    arrays={};offset=4+size
    for field in header.get('fields',[]):
        if not isinstance(field,dict):raise ValueError('invalid command field schema')
        n=field.get('name');expected='i64' if n=='frame_index' else 'f32'
        if not isinstance(n,str) or n not in SHAPES or n in arrays or field.get('dtype')!=expected or field.get('shape')!=list(SHAPES[n]):raise ValueError('invalid/duplicate command field')
        dtype=DTYPES[expected];count=int(np.prod(SHAPES[n]));end=offset+count*dtype.itemsize
        if end>len(message):raise ValueError('truncated command payload')
        arrays[n]=np.frombuffer(message,dtype=dtype,count=count,offset=offset).copy();offset=end
    if set(arrays)!=set(SHAPES) or offset!=len(message):raise ValueError('missing hand/body fields or trailing payload')
    return CommandFrame(arrays['token_state'],arrays['left_hand_joints'],arrays['right_hand_joints'],int(arrays['frame_index'][0]),observation_time_s,source)
