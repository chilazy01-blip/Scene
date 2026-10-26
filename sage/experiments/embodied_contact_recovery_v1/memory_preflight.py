import os
import sys
import resource
from pathlib import Path
from .work import R,E,finish
from sage.experiments.embodied_continuous_v2 import controller as c

work=Path(os.environ['CONTINUOUS_JOB_DIR'])
os.environ['NP_ROOT']=str(R)
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
from target_adapter import install
install('A','gain_translation',work/'model_setup')
from ik import pipeline as p
from ik import sim
import mujoco
states=[]
def memory(tag):
    row={line.split(':')[0]:line.split(':')[1].strip() for line in Path('/proc/self/status').read_text().splitlines() if line.startswith(('VmRSS','VmSize','VmPeak','VmHWM'))}
    states.append({'stage':tag,**row})
memory('after_adapter')
m,d,ctrl=sim.build_sim(spawn=(-1.3243,.071))
memory('after_build')
ik=sim.ArmIK6(m,ctrl)
memory('after_ik_scratch')
runner=p.HybridRunner(m,d,ctrl,ik,video=None,snapshots=False,sim_limit=300,wall_limit=850)
memory('after_runner_no_physics')
other=mujoco.MjData(m)
memory('after_planner_scratch')
report={'passed':True,'physics_steps':0,'memory_states':states,'limits':resource.getrlimit(resource.RLIMIT_AS),
        'maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'model_arena_bytes':getattr(m,'narena',None)}
c.write(E/'MEMORY_PREFLIGHT.json',report);finish(report)
