from copy import deepcopy
from pathlib import Path
import hashlib
import json
import numpy as np
from sage.experiments.codex_trellis_scene_v2.p021_full_workflow import write as write_json, utc

ROOT=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_round2_20260913_v1')
P1=ROOT.with_name('embodied_phase1_20260913_v1')
PACKAGE=P1/'package_v3'
SCHEMA='scene-task-config/v2'
VERSION='round2-controller-v1'

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()

def default(task, identifier='pilot'):
    arm=task=='pick_place'
    return dict(schema=SCHEMA,case_id=identifier,layout_id='L00',initialization_id='I0',split='development',
        task=task,robot='panda' if arm else 'stretch2',controller_version=VERSION,seed=20260913,
        coordinate_frame='world_z_up_m',scene_variant='repaired',physics_only=True,dt_s=.001,
        control_interval_s=.001,record_interval_s=.02,max_duration_s=25. if arm else 60.,
        start=[.78,1.48,.88] if arm else [4.95,.85,.004],goal=[.78,1.25,.88] if arm else [1.97,1.98],
        start_yaw_rad=0. if arm else 3.141592653589793,arm_base=[.55,1.92,.77],arm_yaw_rad=-np.pi/2,
        grasp_yaw_rad=0.,object_poses={},mass_multiplier=1.,friction_multiplier=1.,explicit_contact_pairs=False,
        controller_gain_multiplier=1.,support_owner='explicit_desk',
        allowed_robot_contact_owners=['base','base_link','task_book','explicit_area_rug'],
        allowed_robot_contact_geoms=['floor','robot_mount'],
        acceptance=dict(goal_xy_tolerance_m=.06 if arm else .08,max_final_speed_m_s=.03 if arm else .04,
            stable_seconds=1.,max_robot_scene_penetration_m=.003,min_lift_m=.08,
            min_bilateral_force_n=1.,min_bilateral_seconds=.05),
        observation_policy='privileged state; not a visual policy',material_measured=False)

def validate(config):
    c=deepcopy(config)
    required=set(default(c.get('task')))
    if required-set(c):raise ValueError('Missing configuration fields: '+str(sorted(required-set(c))))
    if c['schema']!=SCHEMA or c['task'] not in ('navigate','pick_place'):raise ValueError('Invalid schema/task')
    if c['controller_version']!=VERSION:raise ValueError('Unknown controller version')
    if c['coordinate_frame']!='world_z_up_m':raise ValueError('Unsupported coordinate frame')
    if c['scene_variant'] not in ('baseline','repaired'):raise ValueError('Invalid collider variant')
    for key,n in [('start',3),('goal',3 if c['task']=='pick_place' else 2),('arm_base',3)]:
        a=np.asarray(c[key],float)
        if a.shape!=(n,) or not np.isfinite(a).all():raise ValueError('Invalid '+key)
        if not (0<a[0]<5.8 and 0<a[1]<5):raise ValueError('Outside room: '+key)
    for key in ('start_yaw_rad','arm_yaw_rad','grasp_yaw_rad','mass_multiplier','friction_multiplier','controller_gain_multiplier'):
        if not np.isfinite(c[key]):raise ValueError('Nonfinite '+key)
    if not (.1<=c['mass_multiplier']<=3 and .05<=c['friction_multiplier']<=3 and .05<=c['controller_gain_multiplier']<=2):raise ValueError('Multiplier out of domain')
    if c['dt_s']!=.001 or c['control_interval_s']!=.001 or c['record_interval_s']!=.02:raise ValueError('Frozen robot solver/control/record schedule required')
    if not (0<c['max_duration_s']<=(25 if c['task']=='pick_place' else 60)):raise ValueError('Invalid duration')
    for pose in c['object_poses'].values():
        from sage.experiments.embodied_scene_v1.package import rigid
        rigid(pose)
    if c['acceptance']!=default(c['task'])['acceptance']:raise ValueError('Acceptance is frozen for this protocol')
    json.dumps(c,allow_nan=False)
    return c

def checkpoint(stage, **fields):
    path=ROOT/'CHECKPOINT.json';c=json.loads(path.read_text())
    c.update(stage=stage,updated_at=utc(),**fields);write_json(path,c)

def ledger(row, root=None):
    import os
    row=dict(at=utc(),**row)
    directory = Path(root) if root is not None else ROOT
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'CASE_LEDGER.jsonl').open('a') as f:
        f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');f.flush();os.fsync(f.fileno())
