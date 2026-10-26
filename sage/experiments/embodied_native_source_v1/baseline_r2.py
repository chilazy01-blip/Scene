"""Original human scene and low-level actions; no reference adaptation or WBC."""
import inspect
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import mujoco
from .runtime import N,J,read,digest
from sage.experiments.embodied_expert_task_v1.source_demo import load_demo
from sage.experiments.embodied_expert_task_v1.quality import names_and_roles
from sage.experiments.embodied_expert_task_v2.expert_offset import qpos_mapping
from sage.experiments.embodied_fb2_repair_v1.initialization import refresh_and_verify
from sage.experiments.embodied_fb2_repair_v1.quality import measure
from sage.experiments.embodied_fb2_repair_v1.torque_audit import TorqueAudit

def state(data):
    return np.r_[data.time,data.qpos.copy(),data.qvel.copy()]

def create_runtime():
    from humanoidmimicgen.dataset_playback import PlaybackConfig,ActionEnv
    from humanoidmimicgen.wbc_runtime import get_env
    import onnxruntime
    def no_policy(*a,**kw):raise RuntimeError('recorded_baseline_forbids_WBC')
    onnxruntime.InferenceSession=no_policy
    proposal=read(J/'APPROVED_PROPOSAL.json')
    assert digest(proposal['source_diagnostic']['local_file'])==proposal['source_diagnostic']['sha256']
    source=load_demo(proposal['source_diagnostic']['local_file'])
    config=PlaybackConfig.from_dict(source['config'])
    config.sim_frequency=200;config.action_source='recorded'
    config.save_video=config.enable_onscreen=config.enable_offscreen=False
    sync=get_env(config,onscreen=False,offscreen=False)
    env=ActionEnv(sync,None,default_base_height=config.controller_initial_base_height)
    env.reset(seed=source['seed'])
    env.reset_to(dict(states=source['arrays']['states'][0].copy(),model_file=source['xml']))
    base=env.base_env;model=base.sim.model._model;data=base.sim.data._data
    assert model.nq==57 and model.nv==55 and model.nu==43 and model.opt.timestep==.005
    assert np.array_equal(state(data),source['arrays']['states'][0])
    initialized=refresh_and_verify(base)
    mapping=qpos_mapping(model,sync.robot_model)
    names,roles=names_and_roles(model,set(base.box.mj_obj.contact_geoms))
    groups={k:list(map(int,sync.robot_model.get_joint_group_indices(k))) for k in
            ('lower_body','upper_body','left_arm','right_arm','left_hand','right_hand')}
    controllers=base.robots[0].composite_controller.part_controllers
    attributes={k:dict(attributes={a:np.asarray(getattr(controllers[k],a)).tolist()
                for a in ('kp','kd')}) for k in ('legs','torso','left','right')}
    inspection=dict(groups=groups,controllers=attributes)
    limits=read(N/'prepared/phase_feedback_20261007/wbc_intent_r1/PHYSICAL_PLAN_R1.json')['limits']
    formula=inspect.getsource(type(base)._check_success)
    scene_formula=inspect.getsource(type(base.scene).success)
    assets={}
    for element in ET.fromstring(base.sim.model.get_xml()).iter():
        value=element.attrib.get('file')
        if value:
            path=Path(value).resolve();assert path.is_file(),str(path)
            assets[str(path)]=digest(path)
    contract=dict(source_sha256=source['sha256'],source_seed=source['seed'],
        embedded_source_xml_sha256=hashlib.sha256(source['xml'].encode()).hexdigest(),
        nq=model.nq,nv=model.nv,nu=model.nu,dt=float(model.opt.timestep),control_dt=.02,
        qpos_by_pin=mapping.tolist(),joint_names=list(sync.robot_model.joint_names),
        names=names,roles=roles,inspection=inspection,limits=limits,
        object_body_id=int(base.obj_body_id[base.box.mj_obj.name]),
        object_mass_kg=float(model.body_mass[base.obj_body_id[base.box.mj_obj.name]]),
        scene_success_source=scene_formula,resolved_asset_sha256=assets,
        task_predicate_source=formula,task_predicate_sha256=hashlib.sha256(formula.encode()).hexdigest(),
        initialized=initialized,mode='recorded_low_level_actions',WBC_forward_allowed=False,
        expected_commands=689,expected_states=690,terminal_window_requires_full_half_second=True,
        source_states_used_for='initialization, comparison and root-drift reference only; never intermediate live state writes')
    obs=env.observe()
    assert np.array_equal(obs['q'],data.qpos[mapping].astype('f4').astype('f8'))
    assert np.array_equal(obs['dq'],data.qvel[mapping-1].astype('f4').astype('f8'))
    return env,source,contract,TorqueAudit(model,mapping,inspection)

def quality(model,scratch,live,source,contract,command):
    scratch.time=live.time;scratch.qpos[:]=live.qpos;scratch.qvel[:]=live.qvel
    scratch.ctrl[:]=live.ctrl;scratch.qacc_warmstart[:]=live.qacc_warmstart
    mujoco.mj_forward(model,scratch)
    states=source['arrays']['states']
    root=np.array([np.interp(live.time,states[:,0],states[:,1+k]) for k in range(3)])
    return measure(model,scratch,contract['names'],contract['roles'],contract['limits'],
                   np.array(contract['qpos_by_pin']),command,root)
