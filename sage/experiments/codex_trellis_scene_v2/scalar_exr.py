"""Read Blender's untransformed scalar V EXR without modifying the artifact."""
from pathlib import Path
import os
import struct
import numpy as np


def read_scalar_exr(path):
    os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
    import cv2
    data=bytearray(Path(path).read_bytes());offset=8;channels=[]
    if data[:4] != b'v/1\x01':
        raise ValueError('Invalid EXR magic')
    while data[offset]:
        end=data.index(0,offset);key=bytes(data[offset:end]);offset=end+1
        end=data.index(0,offset);offset=end+1
        size=struct.unpack_from('<I',data,offset)[0];offset+=4
        if key == b'channels':
            if data[offset:offset+2] != b'V\0' or data[offset+18] != 0:
                raise ValueError('Expected a single scalar V channel')
            data[offset]=ord('Y');channels.append(offset)
        offset+=size
    if len(channels) != 1:
        raise ValueError('Missing scalar EXR channel')
    array=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_UNCHANGED)
    if array is None or array.ndim != 2 or not np.isfinite(array).all():
        raise ValueError('Invalid scalar EXR payload')
    return array
