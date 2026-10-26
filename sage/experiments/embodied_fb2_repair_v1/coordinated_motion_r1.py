"""Persistent coordinated commands, checked braking, hold and task rejoining."""
import numpy as np
from .coordinated_path_r1 import CoordinatedPlanner,Route,Segment
from .motion_r3 import StopTrajectory


class NoSafeContinuation(RuntimeError):
    pass


class CoordinatedGovernor:
    def __init__(self,initial,indices,lower,upper,vmax,amax,dt=.02,trim_indices=(),velocity=None,acceleration=None,max_duration=2.8):
        self.indices=np.asarray(indices,dtype=int);self.q=np.asarray(initial,dtype=float)[self.indices].copy()
        self.planner=CoordinatedPlanner(np.asarray(lower)[self.indices],np.asarray(upper)[self.indices],vmax,amax,dt,max_duration=max_duration)
        self.v=np.zeros_like(self.q) if velocity is None else np.asarray(velocity,dtype=float).copy()
        self.a=np.zeros_like(self.q) if acceleration is None else np.asarray(acceleration,dtype=float).copy()
        self.last_step_velocity=self.v.copy();self.dt=dt;self.mode='track';self.route=None;self.elapsed=0.
        self.anchor=None;self.hold_elapsed=0.;self.ready=0;self.trim=np.zeros_like(self.q)
        self.trim_mask=np.isin(self.indices,trim_indices);self.rejoin_required=False
        self.last_validation=None;self.last_rejection=None;self.sequence=0;self.task_route_admitted=False
        if np.any(self.q<self.planner.lower) or np.any(self.q>self.planner.upper):raise ValueError('initial_command_outside_range')

    def _select(self,candidates,validate,approach=False):
        for candidate in candidates:
            result=validate(candidate,0.,approach)
            if result['passed']:
                self.last_validation=result
                return candidate
            self.last_rejection=result
        return None

    def _commit(self,route):
        q,v,a=route.sample(0.)
        if not all(np.allclose(x,y,rtol=0,atol=1e-9) for x,y in [(q,self.q),(v,self.v),(a,self.a)]):
            raise NoSafeContinuation('noncontinuous_route_splice')
        self.route=route;self.elapsed=0.;self.sequence+=1

    def _brake(self,actual,velocity,validate):
        route=self._select(self.planner.stop_candidates(self.q,self.v,self.a),validate)
        if route is None:raise NoSafeContinuation('no_geometrically_valid_bounded_command_stop')
        measured=StopTrajectory(actual,velocity,self.planner.amax,self.planner.lower,self.planner.upper)
        self.anchor=measured.endpoint.copy();self.hold_elapsed=0.;self.ready=0;self.trim[:]=0.
        self.rejoin_required=True;self.mode='brake';self._commit(route)

    def _advance(self,requested):
        previous=self.q.copy();old_velocity=self.last_step_velocity.copy()
        next_time=min(self.route.duration,self.elapsed+self.dt)
        q,v,a=self.route.sample(next_time);discrete_v=(q-previous)/self.dt;discrete_a=(discrete_v-old_velocity)/self.dt
        if np.any(q<self.planner.lower-1e-9) or np.any(q>self.planner.upper+1e-9) or np.any(abs(discrete_v)>self.planner.vmax+1e-8) or np.any(abs(discrete_a)>self.planner.amax+1e-7):
            raise NoSafeContinuation('final_command_history_bound_violation')
        # State commits only after all bounds and geometric checks passed.
        self.q=q;self.v=v;self.a=a;self.last_step_velocity=discrete_v;self.elapsed=next_time
        result=np.asarray(requested,dtype=float).copy();result[self.indices]=q
        return result,dict(applied=q.copy(),requested=np.asarray(requested)[self.indices].copy(),velocity=discrete_v.copy(),acceleration=discrete_a.copy(),continuous_velocity=v.copy(),continuous_acceleration=a.copy(),common_time=next_time,route_duration=self.route.duration,route_sequence=self.sequence)

    def step(self,actual,velocity,requested,task_target,feasible,safety,validate,allow_resume=True,waypoints=(),tracking_tolerance=.1):
        actual=np.asarray(actual)[self.indices];velocity=np.asarray(velocity)[self.indices]
        requested=np.asarray(requested,dtype=float);nominal=np.asarray(task_target)[self.indices]
        desired=requested[self.indices];entry=False;resumed=False;self.task_route_admitted=False
        tracking_error=float(np.max(abs(actual-self.q)))
        trigger=not feasible or not safety['safe_to_approach'] or tracking_error>tracking_tolerance
        if self.mode in ('track','rejoin') and trigger:
            self._brake(actual,velocity,validate);entry=True
        if self.mode in ('track','rejoin'):
            unchanged=self.route is not None and np.max(abs(self.route.sample(self.route.duration)[0]-desired))<1e-10
            continuation=validate(self.route,self.elapsed,True) if self.route is not None else dict(passed=False)
            if unchanged and continuation['passed']:
                self.task_route_admitted=True;self.last_validation=continuation
            else:
                candidates=self.planner.target_candidates(self.q,self.v,self.a,desired,(np.asarray(x)[self.indices] for x in (waypoints() if callable(waypoints) else waypoints)))
                route=self._select(candidates,validate,approach=True)
                if route is not None:
                    # Every accepted candidate includes its deceleration to rest.
                    self._commit(route);self.task_route_admitted=True
                elif continuation['passed']:
                    self.last_validation=continuation
                    self.last_rejection=self.last_rejection or dict(reason='new_target_not_admitted')
                else:
                    self._brake(actual,velocity,validate);entry=True
        if self.mode=='brake':
            self.hold_elapsed+=self.dt
            if not validate(self.route,self.elapsed,False)['passed']:
                raise NoSafeContinuation('moving_frame_invalidated_checked_brake')
            if self.elapsed>=self.route.duration-1e-12:self.mode='hold'
        if self.mode=='hold':
            self.hold_elapsed+=self.dt;speed=float(np.max(abs(velocity)));error=float(np.max(abs(actual-self.anchor)))
            if self.hold_elapsed>=.15 and speed<=.05 and error>.01:
                increment=np.clip((self.anchor-actual)*self.dt,-.01*self.dt,.01*self.dt)
                self.trim[self.trim_mask]=np.clip(self.trim[self.trim_mask]+increment[self.trim_mask],-.03,.03)
            # Trim is a planned endpoint, never a post-planner joint correction.
            self.trim=np.clip(self.trim,self.planner.lower-self.anchor,self.planner.upper-self.anchor)
            settled=speed<=.05 and error<=.01
            self.ready=self.ready+1 if settled and feasible and safety['safe_to_approach'] else 0
            if self.ready>=5 and allow_resume:
                route=self._select(self.planner.target_candidates(self.q,self.v,self.a,desired,(np.asarray(x)[self.indices] for x in (waypoints() if callable(waypoints) else waypoints))),validate,True)
                if route is not None:self._commit(route);self.mode='rejoin';resumed=True
            if self.mode=='hold':
                route=self._select(self.planner.target_candidates(self.q,self.v,self.a,self.anchor+self.trim),validate)
                if route is None:raise NoSafeContinuation('no_checked_hold_or_friction_trim_path')
                self._commit(route)
        if self.route is None:raise NoSafeContinuation('missing_checked_route')
        command,trajectory=self._advance(requested)
        task_error=float(np.max(abs(actual-nominal)))
        # Rejoining is a task condition, distinct from stopping at the anchor.
        if self.mode=='rejoin' and not resumed and task_error<=tracking_tolerance and feasible and safety['safe_to_approach']:
            self.mode='track';self.rejoin_required=False
        phase_allowed=self.mode=='track' and not entry and not self.rejoin_required and self.task_route_admitted
        return command,dict(mode=self.mode,entry=entry,phase_advance_allowed=phase_allowed,
                            rejoin_started=resumed,rejoin_required=self.rejoin_required,task_route_admitted=self.task_route_admitted,
                            task_error=task_error,actual_command_error=tracking_error,
                            fixed_anchor=None if self.anchor is None else self.anchor.copy(),
                            arm_hold_trim=self.trim.copy(),ready_ticks=self.ready,
                            trajectory=trajectory,prospective_validation=self.last_validation,
                            last_candidate_rejection=self.last_rejection,
                            physical_braking_certified=False)
