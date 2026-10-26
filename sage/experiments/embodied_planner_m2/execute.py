"""State-triggered pick/place with actual actuator execution and every failure kept."""
from pathlib import Path
import time
import traceback

import h5py
import mujoco
import numpy as np
from scipy.spatial.transform import Rotation

from sage.experiments.embodied_scene_bridge.contracts import read, write, digest, require
from .environment import ExecutionEnvironment
from .planner import JointPlanner, PlanningFailure


class ExecutionFailure(RuntimeError):
    pass


class Runner:
    def __init__(self, env, protocol, seed):
        self.env,self.protocol = env,protocol
        self.planner=JointPlanner(env,protocol['planner'],seed)
        self.states=[env.state()]
        self.proprio=[env.observe()['proprio']]
        self.actions=[];self.phases=[];self.events=[]
        self.last_q=env.data.qpos[env.ctrl.qi].copy()
        self.last_grip=.04
        self.last_command_velocity=np.zeros(7)

    def event(self, phase, **fields):
        self.events.append(dict(phase=phase,time_s=float(self.env.data.time),**fields))
        print(self.events[-1],flush=True)

    def tick(self, q, grip, phase):
        e=self.env
        if e.data.time>=self.protocol['execution']['max_simulation_seconds']:
            raise ExecutionFailure('episode_timeout:'+phase)
        action=np.r_[q,grip]
        velocity=(action[:7]-self.last_q)/.05
        acceleration=(velocity-self.last_command_velocity)/.05
        if max(abs(velocity))>self.protocol['execution']['max_joint_target_rate_rad_s']+1e-8:
            raise ExecutionFailure('command_rate_limit:'+phase)
        if max(abs(acceleration))>self.protocol['execution']['max_joint_acceleration_rad_s2']+1e-8:
            raise ExecutionFailure('command_acceleration_limit:'+phase)
        e.step(action)
        self.actions.append(action);self.states.append(e.state());self.proprio.append(e.observe()['proprio']);self.phases.append(phase)
        self.last_q=np.asarray(q).copy();self.last_grip=grip
        self.last_command_velocity=velocity
        if e.metrics['floor_contact']:
            raise ExecutionFailure('target_floor_contact:'+phase)
        if e.metrics['forbidden_contact']:
            raise ExecutionFailure('forbidden_contact:'+phase)

    def hold_until(self, condition, timeout, phase, q=None, grip=None, minimum=.0):
        q=self.last_q.copy() if q is None else q
        grip=self.last_grip if grip is None else grip
        began=float(self.env.data.time)
        while self.env.data.time-began<timeout-1e-8:
            self.tick(q,grip,phase)
            if self.env.data.time-began>=minimum and condition():
                self.event(phase,status='condition_met',elapsed_s=float(self.env.data.time)-began)
                return
        raise ExecutionFailure('phase_timeout:'+phase)

    def move(self, position, phase, grip, held=False, allow_fingers=False, allow_support=False):
        e=self.env
        q,error=e.ctrl.ik(position,e.data.qpos[e.ctrl.qi])
        if error>.015:
            raise PlanningFailure('IK_budget_unsolved:'+phase+':'+str(error))
        attachment=np.linalg.inv(e.grip_pose())@e.target_pose() if held else None
        # Plan with measured finger positions when carrying, preserving the
        # physical gap caused by the object rather than predicting zero width.
        planning_grip=float(abs(e.data.qpos[e.qi[-2:]]).mean()) if held else grip
        path=self.planner.plan(q,phase,planning_grip,attachment,allow_fingers,allow_support,command_q=self.last_q)
        self.event(phase,status='path_ready',waypoints=len(path),target_xyz=list(map(float,position)),ik_residual=error)
        max_rate=self.protocol['execution']['max_joint_target_rate_rad_s']
        max_acc=self.protocol['execution']['max_joint_acceleration_rad_s2']
        for first,last in zip(path[:-1],path[1:]):
            distance=float(max(abs(last-first)))
            duration=max(.10,1.5*distance/max_rate,np.sqrt(6*distance/max_acc))
            steps=max(2,int(np.ceil(duration/.05)))
            for k in range(1,steps+1):
                a=k/steps;s=a*a*(3-2*a)
                self.tick(first+(last-first)*s,grip,phase)
        self.hold_until(lambda: (max(abs(e.data.qpos[e.ctrl.qi]-q))<.025
                                and np.linalg.norm(e.grip_pose()[:3,3]-position)<.008),
                        2.,phase+'_tracking',q=q,grip=grip)

    def execute(self):
        e=self.env
        self.hold_until(lambda: np.linalg.norm(e.data.qvel[e.target_vi:e.target_vi+3])<.02,
                        2.,'settle',minimum=.3)
        actual=e.target_pose()
        yaw=Rotation.from_matrix(actual[:3,:3]).as_euler('xyz')[2]
        e.ctrl.target_rot=Rotation.from_euler('z',yaw).as_matrix()@np.diag([1.,-1.,-1.])
        center=actual[:3,3].copy();height=e.task['grasp_height_offset_m']
        self.move(center+[0,0,height+.12],'approach',.04)
        center=e.target_pose()[:3,3].copy()
        self.move(center+[0,0,height],'descend',.04,allow_fingers=True)
        self.hold_until(lambda:e.bilateral_streak>=.08,3.,'close',grip=0.,minimum=.5)
        self.event('grasp',pad_forces_n=e.last_pad_forces,object_xyz=e.target_pose()[:3,3].tolist())
        grip_xyz=e.grip_pose()[:3,3].copy()
        self.move(grip_xyz+[0,0,.14],'lift',0.,held=True,allow_fingers=True,allow_support=True)
        if e.metrics['max_lift_m']<e.task['success']['min_lift_m']:
            raise ExecutionFailure('grasp_did_not_lift_object')
        if min(e.last_pad_forces)<=e.task['success']['min_bilateral_force_n']:
            raise ExecutionFailure('grasp_lost_after_lift')
        # Recompute object-to-gripper translation from actual contact execution.
        delta=e.grip_pose()[:3,3]-e.target_pose()[:3,3]
        raised=np.asarray(e.task['goal'])+delta+[0,0,.14]
        self.move(raised,'transfer',0.,held=True,allow_fingers=True)
        delta=e.grip_pose()[:3,3]-e.target_pose()[:3,3]
        place=np.asarray(e.task['goal'])+delta+[0,0,.004]
        self.move(place,'lower',0.,held=True,allow_fingers=True,allow_support=True)
        self.hold_until(lambda:not e.last_finger_contact,3.,'release',grip=.04,minimum=.5)
        grip_xyz=e.grip_pose()[:3,3].copy()
        self.move(grip_xyz+[0,0,.14],'retreat',.04)
        self.hold_until(lambda:e.evaluate()['success'],4.,'settle_goal')
        self.event('complete',result=e.evaluate())


def run_episode(root, name, seed):
    root=Path(root);protocol=read(root/'protocol/PROTOCOL.json')
    require(digest(root/'protocol/PROTOCOL.json')==read(root/'protocol/FREEZE.json')['files']['PROTOCOL.json'],'protocol_changed')
    require(seed in protocol['execution']['seeds'],'unregistered_seed')
    previous=list((root/'episodes').glob('*/ATTEMPT.json'))
    require(len(previous)<protocol['execution']['max_attempts'],'execution_attempt_budget_exhausted')
    out=root/'episodes'/name;out.mkdir(exist_ok=False)
    source=Path(protocol['source_scene'])
    require(digest(source/'model.xml')==protocol['source_xml_sha256'],'source_model_changed')
    result=dict(status='running',seed=seed,source_scene=str(source),source_xml_sha256=protocol['source_xml_sha256'],
                source='privileged_OMPL_planned_expert',development=True,scene_edits=0,object_pose_writes_during_execution=False)
    write(out/'ATTEMPT.json',result)
    began=time.monotonic();runner=None
    try:
        env=ExecutionEnvironment(source);env.reset(seed)
        runner=Runner(env,protocol,seed);runner.execute()
        result.update(status='success' if env.evaluate()['success'] else 'task_failed',result=env.evaluate())
    except PlanningFailure as exc:
        result.update(status='controller_budget_unsolved',error=str(exc),traceback=traceback.format_exc())
    except ExecutionFailure as exc:
        result.update(status='task_failed',error=str(exc),traceback=traceback.format_exc())
    except BaseException as exc:
        result.update(status='engineering_error',error=str(exc),traceback=traceback.format_exc())
    finally:
        if runner is not None:
            env=runner.env
            result.update(result=env.evaluate(),forbidden_pairs=env.forbidden_pairs,max_forbidden_penetration_m=env.max_penetration,
                          simulator_warnings=[dict(index=i,count=int(w.number)) for i,w in enumerate(env.data.warning) if w.number],
                          actions=len(runner.actions),observations=len(runner.states),physical_seconds=float(env.data.time))
            with h5py.File(out/'trajectory.h5','w') as h:
                h.attrs.update(schema='M2-development-episode/v1',source='privileged_OMPL_planned_expert',success=result['status']=='success',
                               seed=seed,physics_dt_s=.001,action_dt_s=.05,state_spec=int(env.mask))
                h.create_dataset('action',data=np.asarray(runner.actions).reshape(-1,8),compression='gzip')
                h.create_dataset('observation/proprio',data=np.asarray(runner.proprio),compression='gzip')
                h.create_dataset('observation/time',data=np.arange(len(runner.states))*.05)
                h.create_dataset('privileged/state',data=np.asarray(runner.states),compression='gzip')
                h.create_dataset('privileged/audit_1khz',data=np.asarray(env.audit_rows).reshape(-1,11),compression='gzip')
                h.create_dataset('privileged/contacts_1khz',data=np.asarray(env.contact_rows).reshape(-1,11),compression='gzip')
                h.create_dataset('privileged/phase',data=np.asarray(runner.phases,dtype=h5py.string_dtype()))
            write(out/'PLANS.json',runner.planner.records);write(out/'EVENTS.json',runner.events)
            write(out/'GEOMS.json',{str(i):dict(name=env.model.geom(i).name,owner=env.owner[i]) for i in range(env.model.ngeom)})
        result['wall_seconds']=time.monotonic()-began
        write(out/'ATTEMPT.json',result)
    return result
