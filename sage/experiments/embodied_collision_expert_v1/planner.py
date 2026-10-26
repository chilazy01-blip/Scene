"""Mink 0.0.5 task QP reduced to fourteen arm hinges.

Only a private kinematic configuration is updated. Floating base, lower body,
hands and object have zero decision increments; the physical model is never
integrated or overwritten here. Native PD remains the physical actuator driver.
"""
import numpy as np
import mujoco
import mink
import qpsolvers
from .distance_limit import SignedDistanceLimit


class PlanningRejected(ValueError):
    pass


class ArmPlanner:
    def __init__(self, context):
        self.c = context
        self.m = context.m
        self.config = mink.Configuration(self.m)
        self.arm = np.array([r['pin'] for r in context.rows if r['group'] == 'upper'])
        self.qadr = context.qpos[self.arm]
        self.dadr = context.qvel[self.arm]
        self.tasks = [mink.FrameTask('gripper0_'+s+'_'+s+'_hand_palm_link', 'body',
                                    position_cost=10., orientation_cost=1., lm_damping=.01)
                      for s in ['left', 'right']]
        self.local = [self.m.geom_pos[self.m.geom('gripper0_'+s+'_g0_col').id].copy()
                      for s in ['left','right']]
        self.hand_geoms = {s:{g for g in range(self.m.ngeom)
                              if self.m.body(self.m.geom_bodyid[g]).name.startswith('gripper0_'+s)}
                           for s in ['left','right']}
        active = [g for g in range(self.m.ngeom)
                  if self.m.geom_contype[g] or self.m.geom_conaffinity[g]]
        robot = [g for g in active if self.m.geom_bodyid[g] in context.robot_bodies]
        movable = [g for g in robot if self.m.body(self.m.geom_bodyid[g]).name.startswith('gripper0_')
                   or any(t in self.m.body(self.m.geom_bodyid[g]).name for t in
                          ['shoulder','elbow','wrist'])]
        supports = [self.m.geom('fb2_'+s+'_top').id for s in ['source','target']]
        self.object = self.m.geom('fb2_box_geom').id
        self.self_limit = SignedDistanceLimit(self.m, [(movable,robot)],
                              minimum_distance_from_collisions=.003, collision_detection_distance=.04)
        # Mink removes weld/parent pairs; preserve native explicit exclusions too.
        excluded = set(map(int,self.m.exclude_signature))
        def allowed(pair):
            b1,b2=sorted(int(self.m.geom_bodyid[g]) for g in pair)
            return ((b1 << 16) + b2) not in excluded
        self.self_limit.geom_id_pairs=sorted(set(p for p in self.self_limit.geom_id_pairs if allowed(p)))
        self.self_limit.max_num_contacts=len(self.self_limit.geom_id_pairs)
        self.support_limit=SignedDistanceLimit(self.m,[(movable,supports)],
                              minimum_distance_from_collisions=.035,collision_detection_distance=.09)
        nonhands=[g for g in movable if not any(g in h for h in self.hand_geoms.values())]
        self.object_limits={grasp:SignedDistanceLimit(self.m,
                            [(nonhands if grasp else movable,[self.object])],
                            minimum_distance_from_collisions=.005,collision_detection_distance=.035)
                            for grasp in [False,True]}
        self.grasp_limit=SignedDistanceLimit(self.m,[(sorted(set().union(*self.hand_geoms.values())),[self.object])],minimum_distance_from_collisions=-.004,collision_detection_distance=.02)
        self.solves=0

    def step(self, measured_qpos, previous_reference, centers, rotations, hand_reference,
             grasp=False, dt=.02):
        q=np.array(measured_qpos,copy=True)
        q[self.c.qpos]=previous_reference
        # Lower body is observed, never synthesized by the arm solver.
        q[self.c.qpos[self.c.lower_indices]]=measured_qpos[self.c.qpos[self.c.lower_indices]]
        q[self.c.qpos[self.c.hand]]=hand_reference[self.c.hand]
        self.config.update(q)
        for i,task in enumerate(self.tasks):
            rot=np.asarray(rotations[i]);pos=np.asarray(centers[i])-rot@self.local[i]
            transform=np.eye(4);transform[:3,:3]=rot;transform[:3,3]=pos
            task.set_target(mink.SE3.from_matrix(transform))
        limits=[self.self_limit,self.support_limit,self.object_limits[bool(grasp)]]
        if grasp:limits.append(self.grasp_limit)
        # Mink 0.0.5 collision h is a velocity bound; this QP solves displacements.
        # Passing a unit interval gives h=gain*distance in displacement units.
        # Native physical/control dt remains .002/.02; arm slew uses dt below.
        problem=mink.build_ik(self.config,self.tasks,1.,damping=1e-5,limits=limits)
        H=problem.P[np.ix_(self.dadr,self.dadr)];f=problem.q[self.dadr]
        G=problem.G[:,self.dadr] if problem.G is not None else np.zeros((0,len(self.dadr)));h=problem.h if problem.h is not None else np.zeros(0)
        finite=np.isfinite(h);G=G[finite];h=h[finite]
        # Native ranges plus at most 1 rad/s reference slew. No other DoF moves.
        lo=np.maximum(self.c.lower[self.arm]-q[self.qadr],-dt)
        hi=np.minimum(self.c.upper[self.arm]-q[self.qadr],dt)
        solution=qpsolvers.solve_qp(H,f,G,h,lb=lo,ub=hi,solver='quadprog')
        self.solves+=1
        if solution is None or not np.isfinite(solution).all():
            raise PlanningRejected('collision_qp_infeasible')
        if len(h) and float(np.max(G@solution-h))>1e-7:
            raise PlanningRejected('collision_qp_constraint_residual')
        q[self.qadr]+=solution
        excess=max(float(np.max(self.c.lower[self.arm]-q[self.qadr])),float(np.max(q[self.qadr]-self.c.upper[self.arm])))
        if excess>1e-10:raise PlanningRejected("qp_native_range_residual")
        q[self.qadr]=np.clip(q[self.qadr],self.c.lower[self.arm],self.c.upper[self.arm]);self.config.update(q)
        result=previous_reference.copy();result[self.arm]=q[self.qadr]
        result[self.c.hand]=hand_reference[self.c.hand]
        self.c.validate(result)
        error=[]
        for i,task in enumerate(self.tasks):
            body=self.m.body(task.frame_name).id;rot=self.config.data.xmat[body].reshape(3,3)
            center=self.config.data.xpos[body]+rot@self.local[i]
            error.append(float(np.linalg.norm(center-centers[i])))
        return result,dict(position_errors_m=error,solves=self.solves,
                           max_reference_delta_rad=float(abs(solution).max()))


def collision_roles(context, data, grasp):
    """Exact native contact geometry, every hand/finger; no force fiction."""
    m=context.m;obj=m.geom('fb2_box_geom').id
    supports={m.geom('fb2_source_top').id,m.geom('fb2_target_top').id}
    hands={g for g in range(m.ngeom) if m.body(m.geom_bodyid[g]).name.startswith('gripper0_')}
    bad=[];min_forbidden=1.
    mujoco.mj_kinematics(m,data);mujoco.mj_collision(m,data)
    for cc in data.contact:
        a,b=int(cc.geom1),int(cc.geom2);pair={a,b};depth=max(0.,-float(cc.dist))
        handobject=obj in pair and bool(pair & hands)
        allowed=(context.floor in pair and bool(pair & context.foot_ids)) or (
            obj in pair and bool(pair & supports)) or (handobject and grasp)
        if not allowed:min_forbidden=min(min_forbidden,float(cc.dist))
        if (not allowed and depth>1e-6) or depth>(.005 if handobject else .01):
            bad.append(dict(geoms=[m.geom(a).name,m.geom(b).name],penetration_m=depth,
                            allowed_role=bool(allowed)))
    return bad,min_forbidden
