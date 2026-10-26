import sys
import numpy as np
import h5py
import mujoco
from .work import E,finish
from sage.experiments.embodied_continuous_v2 import controller as c

reports={}
for name in sys.argv[1:]:
    folder=E/'jobs'/name/'episode'
    m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'))
    with h5py.File(folder/'TRACE.h5','r') as f:
        rows=f['contacts/rows'][:]
        q=f['substep/qpos'][:]
        times=f['substep/time_before'][:]
        adr=m.jnt_qposadr[m.joint('red_block_joint').id]
        xyz=q[:,adr:adr+3]
        quat=q[:,adr+3:adr+7]
        tilt=np.degrees(np.arccos(np.clip(1-2*(quat[:,1]**2+quat[:,2]**2),-1,1)))
        reports[name]={'steps_saved':len(q),'time_start':float(times[0]),'time_end':float(times[-1]),
                       'max_penetration_m':float(max(0,-np.min(rows[:,3]))),
                       'max_contact_force_N':float(np.max(np.linalg.norm(rows[:,7:10],axis=1))),
                       'object_displacement_m':float(np.linalg.norm(xyz[-1]-xyz[0])),
                       'object_max_tilt_deg':float(max(tilt)),
                       'original_job_status':c.read(E/'STATE.json')['jobs'][name]['status']}
c.write(E/'CONTACT_WINDOW_ANALYSIS.json',{'no_integration':True,'windows':reports,'production_accepted':False})
finish({'windows':reports})
