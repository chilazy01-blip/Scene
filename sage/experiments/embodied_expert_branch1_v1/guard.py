"""Candidate code may change references, never the plant or integrator state."""
import ast
import contextlib
import hashlib
import importlib.util
import json
import numpy as np

STATE = ('qpos','qvel','qacc_warmstart','ctrl','qfrc_applied','xfrc_applied')
EXPERT_ACTIVE = 0
FORBIDDEN_MODULES = {'subprocess','socket','requests','urllib','http','ctypes','multiprocessing','os','sys','pathlib','importlib','builtins','time','random'}


def check_source(source):
    tree = ast.parse(source)
    classes = [n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Task']
    if len(classes)!=1:
        raise ValueError('candidate must define one Task class')
    for node in ast.walk(tree):
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            names = [x.name for x in node.names] if isinstance(node,ast.Import) else [node.module or '']
            if any(n.split('.')[0] in FORBIDDEN_MODULES for n in names):
                raise ValueError('candidate imports system/I/O module')
            if isinstance(node,ast.ImportFrom) and node.module=='mujoco' and any(a.name in {'mj_step','mj_step1','mj_step2','mj_resetData','mj_setState'} for a in node.names):
                raise ValueError('candidate imports an integrator/state-injection alias')
        if isinstance(node,ast.Call):
            name = node.func.id if isinstance(node.func,ast.Name) else node.func.attr if isinstance(node.func,ast.Attribute) else ''
            if name in {'exec','eval','compile','open','__import__','mj_step','mj_step1','mj_step2','mj_resetData','mj_setState'}:
                raise ValueError('candidate contains a forbidden operation: '+name)
        if isinstance(node,(ast.Assign,ast.AugAssign,ast.AnnAssign)):
            targets = node.targets if isinstance(node,ast.Assign) else [node.target]
            for target in targets:
                while isinstance(target,ast.Subscript): target=target.value
                if isinstance(target,ast.Attribute) and target.attr in STATE and isinstance(target.value,ast.Name) and target.value.id=='data':
                    raise ValueError('candidate writes physical state: '+target.attr)
    return tree


def plant_digest(model):
    h=hashlib.sha256()
    # Physical parameters most likely to be touched accidentally. Native geometry
    # files, all imported code, model and assets are separately SHA-bound.
    for name in ('body_mass','body_inertia','body_ipos','body_iquat','geom_friction','geom_size','geom_pos','geom_quat',
                 'geom_margin','geom_solref','geom_solimp','geom_contype','geom_conaffinity','jnt_range',
                 'dof_damping','dof_frictionloss','actuator_ctrlrange','actuator_forcerange',
                 'actuator_gainprm','actuator_biasprm','mesh_vert','flex_vert','flex_friction','flex_solref','flex_solimp',
                 'flex_radius','flex_contype','flex_conaffinity','flex_condim','jnt_stiffness','dof_armature','body_gravcomp','qpos0'):
        a=getattr(model,name,None)
        if isinstance(a,np.ndarray):h.update(name.encode());h.update(a.tobytes())
    for name in ('timestep','gravity','iterations','ls_iterations','noslip_iterations','tolerance',
                 'noslip_tolerance','solver','integrator','cone','enableflags','disableflags'):
        h.update(name.encode());h.update(np.asarray(getattr(model.opt,name)).tobytes())
    return h.digest()


class GuardedTask:
    def __init__(self,inner,mj,model,case):
        self._inner=inner;self._mj=mj;self._model=model;self._case=case;self._last_data=None

    def __getattr__(self,name):
        value=getattr(self._inner,name)
        if name not in ('update','synchronize','reference_blocks','hand_targets') or not callable(value):return value
        def call(*args,**kwargs):
            global EXPERT_ACTIVE
            data=next((a for a in args if hasattr(a,'qpos') and hasattr(a,'qvel')),self._last_data)
            self._last_data=data
            before=None if data is None else {k:getattr(data,k).copy() for k in STATE}
            before_time=None if data is None else data.time
            plant=plant_digest(self._model)
            case=json.dumps(self._case,sort_keys=True,allow_nan=False)
            saved={}
            def forbidden(*a,**kw):raise RuntimeError('expert attempted unaccounted integration or state injection')
            try:
                EXPERT_ACTIVE+=1
                for n in ('mj_step','mj_step1','mj_step2','mj_resetData','mj_setState'):
                    if hasattr(self._mj,n):saved[n]=getattr(self._mj,n);setattr(self._mj,n,forbidden)
                result=value(*args,**kwargs)
            finally:
                EXPERT_ACTIVE-=1
                for n,v in saved.items():setattr(self._mj,n,v)
            if plant_digest(self._model)!=plant:
                raise RuntimeError('expert changed frozen physical model')
            if json.dumps(self._case,sort_keys=True,allow_nan=False)!=case:
                raise RuntimeError('expert changed frozen task case or target')
            if data is not None:
                if data.time!=before_time or any(not np.array_equal(getattr(data,k),v) for k,v in before.items()):
                    raise RuntimeError('expert changed physical state rather than references')
            return result
        return call


def load_task(binding,*args):
    global EXPERT_ACTIVE
    from .common import check
    check(binding)
    source=open(binding['path']).read();check_source(source)
    spec=importlib.util.spec_from_file_location('codex_expert_'+binding['sha256'][:16],binding['path'])
    module=importlib.util.module_from_spec(spec)
    mj,model,case=args[:3]
    before=plant_digest(model);case_before=json.dumps(case,sort_keys=True)
    try:
        EXPERT_ACTIVE+=1
        spec.loader.exec_module(module)
        task=module.Task(*args)
    finally:EXPERT_ACTIVE-=1
    if plant_digest(model)!=before or json.dumps(case,sort_keys=True)!=case_before:
        raise RuntimeError('candidate constructor modified plant/case')
    return GuardedTask(task,mj,model,case)
