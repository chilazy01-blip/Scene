"""Register concrete bounded work; scientific and resource gates remain central."""
from pathlib import Path
from .work import R,E
from sage.experiments.embodied_continuous_v2 import controller as c

MOD=Path(__file__).resolve().parent


def environment():
    manifest=c.read(R/'shared/ENV37_MANIFEST.json')
    return ['env','PYTHONPATH='+manifest['target']+':/data/wsj/main/scene',
            'MUJOCO_GL=egl','PYOPENGL_PLATFORM=egl','__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json',
            'GALLIUM_DRIVER=llvmpipe','EGL_PLATFORM=surfaceless','LIBGL_ALWAYS_SOFTWARE=1','LP_NUM_THREADS=2',
            manifest['base_interpreter'],'-B']


def job(module,args=(),files=(),timeout=120,kind='engineering',scope='reversible_engineering',reservation=None,**extra):
    inputs={str(Path(f).resolve()):c.sha(f) for f in [MOD/(module+'.py'),*files]}
    return {'kind':kind,'scope':scope,'pool':'development','timeout_seconds':timeout,
            'reservation':{'service_seconds':timeout+5,**(reservation or {})},'inputs':inputs,
            'argv':environment()+['-m','sage.experiments.embodied_contact_recovery_v1.'+module,*map(str,args)],
            'initial':True,'on_failure':['bootstrap_diagnosis'],'on_success':[],**extra}


def add(jobs,reason):
    result=c.extend_jobs(E,jobs,reason)
    print(result['action'],result.get('job'),result.get('blockers'))
