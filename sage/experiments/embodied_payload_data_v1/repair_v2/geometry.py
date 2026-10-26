"""Isolated whole-body geometry, supported targets and bounded joint planning.

    No function integrates physics or writes a live simulation state. A feasible
    static endpoint remains distinct from a dynamically validated method.
"""
import itertools
import numpy as np
import mujoco
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation


class SceneQuery:
    def __init__(self, model, contract):
        self.m = model
        self.d = mujoco.MjData(model)
        self.c = contract
        self.qmap = np.asarray(contract["qpos_by_pin"])
        self.active = [i for i in range(model.ngeom) if model.geom_contype[i] or model.geom_conaffinity[i]]
        self.roles = contract["roles"]
        self.names = contract["names"]
        self.board = model.geom("shelf_board_1_board").id
        self.bottom = model.geom("box_bottom_coll").id
        self.palms = {s:int(model.geom("gripper0_"+s+"_g0_col").bodyid) for s in ("left","right")}
        self.feet = {s:model.body("robot0_"+s+"_ankle_roll_link").id for s in ("left","right")}
        def massive_subtree(qpos_address):
            joints=np.flatnonzero(model.jnt_qposadr==qpos_address)
            if len(joints)!=1 or model.jnt_type[joints[0]]!=mujoco.mjtJoint.mjJNT_FREE:
                raise ValueError("free_root_binding_required")
            root=int(model.jnt_bodyid[joints[0]])
            result=[]
            for body in range(1,model.nbody):
                ancestor=body
                while ancestor and ancestor!=root:ancestor=int(model.body_parentid[ancestor])
                if ancestor==root and model.body_mass[body]>0:result.append(body)
            return result
        # Collision-less links still contribute mass and rotational inertia.
        self.object_bodies = massive_subtree(50)
        self.robot_bodies = massive_subtree(0)
        self.floor = model.geom("floor").id
        self.object_weight = float(sum(model.body_mass[i] for i in self.object_bodies)*np.linalg.norm(model.opt.gravity))
        self.movers = np.array([g for g in self.active if self.roles[g] in {"robot","hand","foot","object"}],dtype=int)
        self.environment = np.array([g for g in self.active if self.roles[g] not in {"robot","hand","foot","object"}],dtype=int)

    def set(self, q):
        q = np.asarray(q)
        if q.shape != (self.m.nq,) or not np.isfinite(q).all():
            raise ValueError("invalid_configuration")
        self.d.qpos[:] = q
        mujoco.mj_kinematics(self.m,self.d)
        mujoco.mj_comPos(self.m,self.d)

    def pose(self, body):
        return self.d.xpos[body].copy(), self.d.xmat[body].reshape(3,3).copy()

    def footprint(self):
        d,m = self.d,self.m
        if m.geom_type[self.bottom] != mujoco.mjtGeom.mjGEOM_BOX or m.geom_type[self.board] != mujoco.mjtGeom.mjGEOM_BOX:
            raise ValueError("box_board_geometry_required")
        corners = np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1]])*m.geom_size[self.bottom]
        world = corners@d.geom_xmat[self.bottom].reshape(3,3).T+d.geom_xpos[self.bottom]
        local = (world-d.geom_xpos[self.board])@d.geom_xmat[self.board].reshape(3,3)
        masses = m.body_mass[self.object_bodies]
        com = np.average(d.xipos[self.object_bodies],axis=0,weights=masses)
        local_com = (com-d.geom_xpos[self.board])@d.geom_xmat[self.board].reshape(3,3)
        half = m.geom_size[self.board,:2]
        return dict(bottom_margin=float(np.min(half-np.abs(local[:,:2]))),
                    com_margin=float(np.min(half-np.abs(local_com[:2]))),
                    bottom_local=local, board_half=half.copy(),
                    bottom_height=float(np.mean(local[:,2])-m.geom_size[self.board,2]))

    def supported_targets(self, q, margin=.005):
        self.set(q)
        f = self.footprint()
        xy, half = f["bottom_local"][:,:2], f["board_half"]-margin
        lower, upper = -half-xy.min(0), half-xy.max(0)
        if np.any(lower > upper):
            return []
        nearest = np.clip(np.zeros(2), lower, upper)
        center = (lower+upper)/2
        rotation = self.d.geom_xmat[self.board].reshape(3,3).copy()
        result = []
        for shift in (nearest, (nearest+center)/2, center):
            target = np.array(q,copy=True)
            target[50:53] += rotation@np.r_[shift,-f["bottom_height"]]
            if not any(np.max(np.abs(target-x)) < 1e-9 for x in result):
                result.append(target)
        return result

    def level_object(self, q):
        """Align the box bottom with the board, retaining its in-plane heading."""
        self.set(q)
        board = self.d.geom_xmat[self.board].reshape(3,3)
        bottom = self.d.geom_xmat[self.bottom].reshape(3,3)
        heading = board.T@bottom[:,0]
        angle = np.arctan2(heading[1],heading[0])
        desired = board@Rotation.from_euler('z',angle).as_matrix()
        delta = desired@bottom.T
        object_rotation = Rotation.from_quat(np.r_[q[54:57],q[53]]).as_matrix()
        quat = Rotation.from_matrix(delta@object_rotation).as_quat()
        result = np.array(q,copy=True)
        result[53:57] = np.r_[quat[3],quat[:3]]
        return result

    def support_planes(self):
        # Sphere-plane contacts support at projected pad centers. Expanding the
        # hull by a whole sphere radius would invent an unsupported contact patch.
        points = []
        for g in self.active:
            if self.roles[g] != "foot" or self.m.geom_type[g] != mujoco.mjtGeom.mjGEOM_SPHERE:
                continue
            center = self.d.geom_xpos[g]
            radius = self.m.geom_size[g,0]
            gap=center[2]-radius-self.m.geom_pos[self.floor,2]
            if gap > 1e-5 or gap < -.01:
                continue
            points.append(center[:2])
        if len(points) < 3:
            return None
        hull = ConvexHull(points)
        return hull.equations.copy()

    def balance_margin(self, planes=None):
        planes=self.support_planes() if planes is None else planes
        if planes is None:return -1.
        bodies = sorted(set(self.robot_bodies+self.object_bodies))
        com = np.average(self.d.xipos[bodies],axis=0,weights=self.m.body_mass[bodies])
        return float(np.min(-(planes[:,:2]@com[:2]+planes[:,2])))

    def clearance(self, phase="place", margin=.003, source_supports=()):
        """Check every active robot/object-environment pair; no shelf-only shortcut."""
        from .quality import phase_contacts
        m,d = self.m,self.d
        mujoco.mj_collision(m,d)
        contact_rows = [dict(geoms=[self.names[c.geom1],self.names[c.geom2]],distance=float(c.dist),normal_force=0.) for c in d.contact]
        forbidden = phase_contacts(contact_rows,phase,dict(zip(self.names,self.roles)),self.names[self.board],source_supports)
        penetration = max([max(0.,-float(c.dist)) for c in d.contact],default=0.)
        minimum,pair = .3,None
        line = np.zeros(6)
        # The same conservative sphere bound, vectorized before exact distance
        # calls. Pair order and all exclusion/quality rules remain unchanged.
        movers,environment=self.movers,self.environment
        bounds=np.linalg.norm(d.geom_xpos[movers,None,:]-d.geom_xpos[None,environment,:],axis=2)
        bounds-=m.geom_rbound[movers,None]+m.geom_rbound[None,environment]
        bounds[:,m.geom_type[environment]==mujoco.mjtGeom.mjGEOM_PLANE]=-np.inf
        for ai,bi in zip(*np.nonzero(bounds<=minimum)):
            a,b=int(movers[ai]),int(environment[bi])
            if self.roles[a] == "foot" and self.roles[b] == "floor":
                continue
            if self.roles[a] == "object" and ((phase in {"place","release","withdraw","hold"} and b == self.board)
                                               or (phase == "pick" and self.names[b] in source_supports)):
                continue
            # Bounding spheres conservatively skip remote pairs. Plane radius is unbounded.
            if bounds[ai,bi] > minimum:
                continue
            distance = float(mujoco.mj_geomDistance(m,d,a,b,minimum,line))
            if distance < minimum:
                minimum,pair = distance,[self.names[a],self.names[b]]
        return dict(passed=forbidden["passed"] and penetration <= .01 and minimum >= margin,
                    minimum_clearance=minimum,pair=pair,max_penetration=penetration,
                    forbidden=forbidden["violations"])

    def sweep(self, configurations, phase, margin=.003, max_joint_step=.01, max_translation_step=.002, source_supports=()):
        """Dense swept samples; explicitly not a continuous collision certificate."""
        worst = .3
        checks = 0
        for a,b in zip(configurations,configurations[1:]):
            n = max(1,int(np.ceil(np.max(np.abs(b[self.qmap]-a[self.qmap]))/max_joint_step)),
                    int(np.ceil(max(np.linalg.norm(b[:3]-a[:3]),np.linalg.norm(b[50:53]-a[50:53]))/max_translation_step)))
            if n > 2000:
                return dict(passed=False,reason="sweep_sampling_bound",samples=checks)
            for f in np.linspace(0.,1.,n+1):
                q = a*(1-f)+b*f
                for sl in (slice(3,7),slice(53,57)):
                    qb = b[sl] if np.dot(a[sl],b[sl]) >= 0 else -b[sl]
                    q[sl] = a[sl]*(1-f)+qb*f
                    q[sl] /= np.linalg.norm(q[sl])
                self.set(q)
                report = self.clearance(phase,margin,source_supports=source_supports)
                checks += 1
                worst = min(worst,report["minimum_clearance"])
                if not report["passed"]:
                    return dict(passed=False,reason="swept_geometry",samples=checks,first_failure=report)
        return dict(passed=checks>0, samples=checks,minimum_clearance=worst,
                    scope="dense_sampled_geometry_requires_dynamic_validation")


class JointPlacementPlanner:
    """Solve feet, body and both palm poses for fully supported object targets."""
    def __init__(self, query, max_evaluations=100):
        self.query = query
        self.max_evaluations = max_evaluations

    def plan(self, stopped_q, grasp_reference_q, check_deadline=lambda: None):
        query,m = self.query,self.query.m
        qmap = query.qmap
        ids = np.array([*range(22),*range(29,36)]) # legs, waist, arms; fixed grasp fingers
        joints = [int(np.flatnonzero(m.jnt_qposadr == adr)[0]) for adr in qmap[ids]]
        query.set(stopped_q)
        feet = {s:query.pose(b) for s,b in query.feet.items()}
        # Feet are fixed by equality residuals. Keep their measured support
        # polygon fixed inside the optimizer, avoiding discontinuous changes
        # when a trial iterate temporarily lifts a pad by a few micrometres.
        support_planes=query.support_planes()
        if support_planes is None:
            return dict(passed=False,candidates=[],reason="no_static_support_polygon",physical_validated=False)
        query.set(grasp_reference_q)
        palms = {s:query.pose(b) for s,b in query.palms.items()}
        origin = grasp_reference_q[50:53].copy()
        original_rotation = Rotation.from_quat(np.r_[grasp_reference_q[54:57],grasp_reference_q[53]]).as_matrix()
        leveled = query.level_object(grasp_reference_q)
        candidates = []
        for target in query.supported_targets(leveled,margin=.008):
            check_deadline()
            target_rotation = Rotation.from_quat(np.r_[target[54:57],target[53]]).as_matrix()
            rotation_delta = target_rotation@original_rotation.T
            targets = {s:(target[50:53]+rotation_delta@(p-origin),rotation_delta@r) for s,(p,r) in palms.items()}
            seed = stopped_q.copy()
            seed[50:57] = target[50:57]
            # Retain the demonstrated grasp relation; solve root, feet and all arm joints together.
            hand_ids = np.array(query.c["inspection"]["groups"]["left_hand"]+query.c["inspection"]["groups"]["right_hand"])
            seed[qmap[hand_ids]] = grasp_reference_q[qmap[hand_ids]]
            x0 = np.r_[seed[:3],seed[qmap[ids]]]
            low = np.r_[stopped_q[:3]-[.18,.12,.10],m.jnt_range[joints,0]+.006]
            high = np.r_[stopped_q[:3]+[.18,.12,.10],m.jnt_range[joints,1]-.006]
            def unpack(x):
                q = seed.copy();q[:3]=x[:3];q[qmap[ids]]=x[3:];return q
            def residual(x):
                check_deadline()
                query.set(unpack(x));r=[]
                for side,b in query.feet.items():
                    p,rot = query.pose(b);tp,tr = feet[side]
                    r.extend((p-tp)/.002);r.extend(Rotation.from_matrix(rot@tr.T).as_rotvec()/.02)
                for side,b in query.palms.items():
                    p,rot = query.pose(b);tp,tr = targets[side]
                    r.extend((p-tp)/.003);r.extend(Rotation.from_matrix(rot@tr.T).as_rotvec()/.04)
                # Optimize a positive COM margin, rather than hoping an IK-only
                # solution happens to pass the independent 10 mm support gate.
                r.append(max(0.,.015-query.balance_margin(support_planes))/.003)
                r.extend((x-x0)*.03)
                return np.array(r)
            solution = least_squares(residual,np.clip(x0,low+1e-8,high-1e-8),bounds=(low,high),
                                     max_nfev=self.max_evaluations,ftol=1e-7,xtol=1e-7,gtol=1e-7)
            q = unpack(solution.x);query.set(q)
            errors={}
            jp=np.zeros((3,m.nv));jr=jp.copy()
            for side,b in query.palms.items():
                pos,rot=query.pose(b);tp,tr=targets[side]
                mujoco.mj_jacBody(m,query.d,jp,jr,b)
                armids=query.c["inspection"]["groups"][side+"_arm"]
                jac=np.vstack([jp[:,qmap[armids]-1],jr[:,qmap[armids]-1]*.3])
                errors[side]=dict(position=float(np.linalg.norm(pos-tp)),rotation=float(np.linalg.norm(Rotation.from_matrix(rot@tr.T).as_rotvec())),condition=float(np.linalg.cond(jac)))
            foot_errors={s:float(np.linalg.norm(query.pose(b)[0]-feet[s][0])) for s,b in query.feet.items()}
            foot_rotations={s:float(np.linalg.norm(Rotation.from_matrix(query.pose(b)[1]@feet[s][1].T).as_rotvec())) for s,b in query.feet.items()}
            fp=query.footprint();balance=query.balance_margin();clearance=query.clearance("place",.005)
            from .progress import validate_ik, ControlRejected
            try:validate_ik(errors);ik_ok=True
            except ControlRejected:ik_ok=False
            checks=dict(ik=ik_ok,feet=max(foot_errors.values()) <= .002 and max(foot_rotations.values()) <= .02,balance=balance>=.01,
                        supported=fp["bottom_margin"] >= .005 and fp["com_margin"] >= .01,
                        clearance=clearance["passed"])
            candidates.append(dict(passed=all(checks.values()),checks=checks,qpos=q.tolist(),ik=errors,
                                   foot_errors=foot_errors,foot_rotation_errors=foot_rotations,balance_margin=balance,bottom_margin=fp["bottom_margin"],
                                   clearance=clearance,evaluations=solution.nfev))
        return dict(passed=any(c["passed"] for c in candidates),candidates=candidates,
                    physical_validated=False,scope="joint_static_endpoint_not_complete_motion")
