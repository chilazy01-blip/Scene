"""OMPL RRTConnect with MuJoCo validity and dense independent edge checks."""
import time
import mujoco
import numpy as np
from scipy.spatial.transform import Rotation
from ompl import base as ob, geometric as og, util as ou

_OMPL_SEEDED = False

class PlanningFailure(RuntimeError):
    pass


class JointPlanner:
    def __init__(self, env, configuration, seed):
        global _OMPL_SEEDED
        if _OMPL_SEEDED:
            raise RuntimeError('OMPL requires a fresh process per episode; reseeding after sampling is unsafe')
        _OMPL_SEEDED = True
        self.env,self.config = env,configuration
        self.model = env.model
        self.data = mujoco.MjData(self.model)
        self.records = []
        ou.RNG.setSeed(int(seed))
        ou.setLogLevel(ou.LOG_WARN)
        self.bounds = env.model.jnt_range[env.ctrl.joints].copy()
        self.query_count = 0
        self.reject_count = 0

    def _contacts(self, allow_fingers, held, allow_support):
        m,d,e = self.model,self.data,self.env
        bad = []
        for contact in d.contact:
            if contact.dist >= -self.config['invalid_state_penetration_m']:
                continue
            ids=[int(contact.geom1),int(contact.geom2)]
            own=[e.owner[i] for i in ids]
            names=[m.geom(i).name for i in ids]
            allowed=True
            if 'base' in own:
                k=own.index('base');other=1-k
                allowed=(names[other]=='robot_mount' or
                         (allow_fingers and own[other]==e.task['target_body'] and names[k].startswith('finger')))
            elif held and e.task['target_body'] in own:
                other=1-own.index(e.task['target_body'])
                allowed=allow_support and own[other]==e.task['support_body']
            if not allowed:
                bad.append(dict(geoms=names,penetration_m=-float(contact.dist)))
        return bad

    def plan(self, goal_q, phase, grip, held_transform=None, allow_fingers=False, allow_support=False, command_q=None):
        e,m,d = self.env,self.model,self.data
        start_q=e.data.qpos[e.ctrl.qi].copy()
        template=e.data.qpos.copy()
        def check(q, details=False):
            self.query_count+=1
            d.qpos[:]=template
            d.qpos[e.ctrl.qi]=q
            d.qpos[e.qi[-2:]]=[grip,-grip]
            if held_transform is not None:
                mujoco.mj_kinematics(m,d)
                T=np.eye(4);T[:3,:3]=d.site_xmat[e.ctrl.site].reshape(3,3);T[:3,3]=d.site_xpos[e.ctrl.site]
                predicted=T@held_transform
                d.qpos[e.target_qi:e.target_qi+3]=predicted[:3,3]
                d.qpos[e.target_qi+3:e.target_qi+7]=Rotation.from_matrix(predicted[:3,:3]).as_quat()[[3,0,1,2]]
            mujoco.mj_forward(m,d)
            bad=self._contacts(allow_fingers,held_transform is not None,allow_support)
            self.reject_count+=bool(bad)
            return bad if details else not bad
        row=dict(phase=phase,start_q=start_q.tolist(),goal_q=np.asarray(goal_q).tolist(),held_object=held_transform is not None,
                 allow_fingers=allow_fingers,allow_support=allow_support,attempts=[],status='planning')
        self.records.append(row)
        began=time.monotonic();before=self.query_count;reject_before=self.reject_count
        try:
            for label,q in [('start',start_q),('goal',goal_q)]:
                bad=check(q,True)
                if bad:
                    row[label+'_invalid_contacts']=bad
                    raise PlanningFailure('invalid_'+label+'_state:'+phase)
            space=ob.RealVectorStateSpace(7)
            bounds=ob.RealVectorBounds(7)
            for i,(lo,hi) in enumerate(self.bounds):
                bounds.setLow(i,float(lo));bounds.setHigh(i,float(hi))
            space.setBounds(bounds)
            # Euclidean edge length <= .01 implies each joint's increment <= .01.
            space.setLongestValidSegmentFraction(self.config['collision_resolution_max_joint_rad']/space.getMaximumExtent())
            for attempt in range(self.config['planning_attempts_per_segment']):
                ss=og.SimpleSetup(space)
                ss.setStateValidityChecker(lambda state: check(np.array([state[i] for i in range(7)])))
                start=space.allocState();goal=space.allocState()
                for i in range(7):start[i]=float(start_q[i]);goal[i]=float(goal_q[i])
                ss.setStartAndGoalStates(start,goal)
                planner=og.RRTConnect(ss.getSpaceInformation());planner.setRange(self.config['range_rad'])
                ss.setPlanner(planner);ss.setup()
                status=ss.solve(self.config['solve_seconds_per_attempt'])
                row['attempts'].append(dict(attempt=attempt,status=str(status),exact=ss.haveExactSolutionPath()))
                if not ss.haveExactSolutionPath():
                    continue
                path=ss.getSolutionPath()
                coarse=np.array([[path.getState(j)[i] for i in range(7)] for j in range(path.getStateCount())])
                if command_q is not None:
                    # Preserve command continuity across phases. The preceding
                    # command differs slightly from the measured arm pose.
                    # Include that bridge in the same dense collision check.
                    coarse=np.vstack([np.asarray(command_q),coarse])
                    row['command_bridge_start_q']=np.asarray(command_q).tolist()
                dense=[coarse[0]]
                for a,b in zip(coarse[:-1],coarse[1:]):
                    count=max(1,int(np.ceil(max(abs(b-a))/self.config['postcheck_resolution_max_joint_rad'])))
                    dense.extend(a+(b-a)*k/count for k in range(1,count+1))
                for q in dense:
                    if not check(q):
                        raise PlanningFailure('dense_postcheck_rejected:'+phase)
                row.update(status='exact_path_validated',coarse_path=coarse.tolist(),dense_checked_states=len(dense))
                return coarse
            raise PlanningFailure('planner_budget_unsolved:'+phase)
        except BaseException as exc:
            row.update(status='unresolved',error=str(exc))
            raise
        finally:
            row.update(wall_seconds=time.monotonic()-began,validity_queries=self.query_count-before,
                       rejected_queries=self.reject_count-reject_before)
