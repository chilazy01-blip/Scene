"""Lossless public LeRobot rows. Simulator truth stays in the source trace."""
import numpy as np
STATE_FIELDS=['joint_position','joint_velocity','previous_command','base_orientation_wxyz','base_gyro_rps']
def features(metadata):
    joints=metadata['joint_names']
    names=[prefix+'.'+j for prefix in ['q','dq','previous_command'] for j in joints]+['orientation.'+s for s in ['w','x','y','z']]+['gyro.'+s for s in ['x','y','z']]
    result={
        'observation.state':dict(dtype='float64',shape=(136,),names=names),
        'action':dict(dtype='float64',shape=(86,),names=[str(k)+'.'+j for k in range(2) for j in joints]),
        'action.valid':dict(dtype='uint8',shape=(2,),names=['t','t_plus_20ms']),
        'action.command_time':dict(dtype='float64',shape=(2,),names=['t','t_plus_20ms']),
        'source.sensor_time':dict(dtype='float64',shape=(1,),names=['sim_seconds']),
        'next.done':dict(dtype='uint8',shape=(1,),names=['episode_end'])}
    for cam in metadata['cameras']:
        result['observation.images.'+cam]=dict(dtype='image',shape=(256,256,3),names=['height','width','channels'])
        result['observation.intrinsics.'+cam]=dict(dtype='float64',shape=(9,),names=None)
        result['observation.optical_to_base.'+cam]=dict(dtype='float64',shape=(16,),names=None)
    return result
def frame(source,i,cameras):
    t=source['trajectory']
    value={'observation.state':np.concatenate([t[k][i] for k in STATE_FIELDS]),
        'action':t['action_chunk'][i].reshape(86),
        'action.valid':t['action_valid'][i].astype('u1'),
        'action.command_time':t['action_timestamps'][i],
        'source.sensor_time':np.array([t['timestamp'][i]],dtype='f8'),
        'next.done':np.array([t['done'][i]],dtype='u1')}
    for cam in cameras:
        group=source['cameras/'+cam]
        value['observation.images.'+cam]=group['rgb'][i]
        value['observation.intrinsics.'+cam]=group['K'][i].reshape(9)
        value['observation.optical_to_base.'+cam]=group['optical_to_base'][i].reshape(16)
    for name,a in value.items():
        if not np.isfinite(a).all():raise ValueError('nonfinite:'+name)
    return value
