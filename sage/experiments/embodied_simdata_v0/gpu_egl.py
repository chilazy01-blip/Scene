"""Bind EGL to the leased GPU using DRM identity before creating a context."""
import ctypes as C
import os
import uuid as uuid_module
from pathlib import Path

def bind():
    os.environ.setdefault('MUJOCO_GL','egl')
    if os.environ['MUJOCO_GL'] in ('egl','osmesa'):
        os.environ.setdefault('PYOPENGL_PLATFORM',os.environ['MUJOCO_GL'])
    if 'PHASE_GPU_INDEX' not in os.environ:return dict(mode='software')
    os.environ['MUJOCO_GL']='egl'
    os.environ['__EGL_VENDOR_LIBRARY_FILENAMES']='/usr/share/glvnd/egl_vendor.d/10_nvidia.json'
    os.environ['PYOPENGL_PLATFORM']='egl'
    for key in ['LIBGL_ALWAYS_SOFTWARE','GALLIUM_DRIVER','EGL_PLATFORM']:
        os.environ.pop(key,None)
    lib=C.CDLL('libEGL.so.1');lib.eglGetProcAddress.restype=C.c_void_p;lib.eglGetProcAddress.argtypes=[C.c_char_p]
    query=C.CFUNCTYPE(C.c_uint,C.c_int,C.POINTER(C.c_void_p),C.POINTER(C.c_int))(lib.eglGetProcAddress(b'eglQueryDevicesEXT'))
    string=C.CFUNCTYPE(C.c_char_p,C.c_void_p,C.c_int)(lib.eglGetProcAddress(b'eglQueryDeviceStringEXT'))
    binary_ptr=lib.eglGetProcAddress(b'eglQueryDeviceBinaryEXT')
    binary=C.CFUNCTYPE(C.c_uint,C.c_void_p,C.c_int,C.c_int,C.c_void_p,C.POINTER(C.c_int))(binary_ptr) if binary_ptr else None
    devices=(C.c_void_p*16)();n=C.c_int();assert query(16,devices,C.byref(n))
    # Driver information exposes UUID and bus location, independent of CUDA order.
    uuid=os.environ['CUDA_VISIBLE_DEVICES'];pci=None
    for path in Path('/proc/driver/nvidia/gpus').glob('*/information'):
        if uuid in path.read_text():pci=path.parent.name.lower()
    if pci is None:raise RuntimeError('Cannot map leased UUID to PCI address')
    rows=[];selected=None
    for i in range(n.value):
        dev=devices[i];path=string(dev,0x3233) or string(dev,0x3377)
        drm=path.decode() if path else None;bus=None
        if drm:
            sys=Path('/sys/class/drm')/Path(drm).name/'device'
            if sys.exists():bus=sys.resolve().name.lower()
        ext=string(dev,0x3055);device_uuid=None
        if binary is not None and ext and b'EGL_EXT_device_persistent_id' in ext:
            raw=(C.c_ubyte*16)();size=C.c_int()
            if binary(dev,0x335C,16,raw,C.byref(size)) and size.value==16:
                device_uuid='GPU-'+str(uuid_module.UUID(bytes=bytes(raw)))
        rows.append(dict(egl_index=i,drm=drm,pci=bus,uuid=device_uuid,extensions=ext.decode() if ext else None))
        if bus==pci or device_uuid==uuid:selected=i
    if selected is None:raise RuntimeError('EGL device cannot be bound to leased GPU: '+str(rows))
    os.environ['MUJOCO_EGL_DEVICE_ID']=str(selected)
    return dict(mode='leased_gpu',uuid=uuid,pci=pci,egl_index=selected,devices=rows)

def proof(binding):
    from OpenGL import GL
    info=dict(binding=binding,vendor=GL.glGetString(GL.GL_VENDOR).decode(),renderer=GL.glGetString(GL.GL_RENDERER).decode(),version=GL.glGetString(GL.GL_VERSION).decode())
    if binding['mode']=='leased_gpu':
        from .gpu_nvml import inventory
        gpus=inventory();own=[g['uuid'] for g in gpus if str(os.getpid()) in list(map(str,g['process_pids']))]
        info['nvml_owned_context_uuids']=own
        if own!=[binding['uuid']] or 'NVIDIA' not in info['vendor']:raise RuntimeError('EGL context identity mismatch: '+str(info))
    return info
