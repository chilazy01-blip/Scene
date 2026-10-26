"""World-frame contact evidence with explicit force provenance."""
import numpy as np


def object_contact_evidence(query, *, force_semantics, time=None, velocity=None):
    """Read solved forces from query.d without changing or advancing its state.

    The caller must use 'post_state_query' for mj_forward on saved states.
    'integrated_step_world_force' is reserved for the solved step actually used
    by the integrator and must be recorded together with that step's duration.
    """
    import mujoco
    if force_semantics not in {"post_state_query","integrated_step_world_force"}:
        raise ValueError("unknown_force_semantics")
    m,d=query.m,query.d
    velocity = d.qvel if velocity is None else np.asarray(velocity)
    if velocity.shape != (m.nv,) or not np.isfinite(velocity).all():
        raise ValueError("invalid_sample_velocity")
    force_total=np.zeros(3);board_force=np.zeros(3)
    other_load=0.;hands={"left":0,"right":0};hand_force=np.zeros(3)
    contacts=[];approach=0.;jac=np.zeros((3,m.nv));other_jac=jac.copy()
    for i,c in enumerate(d.contact):
        ids=[c.geom1,c.geom2];roles=[query.roles[g] for g in ids]
        force=np.zeros(6);mujoco.mj_contactForce(m,d,i,force)
        contacts.append(dict(geoms=[query.names[g] for g in ids],distance=float(c.dist),normal_force=float(force[0])))
        if "object" not in roles or roles==["object","object"]:
            continue
        objslot=roles.index("object");other=ids[1-objslot]
        world=(c.frame.reshape(3,3).T@force[:3])*(1 if objslot==1 else -1)
        force_total+=world
        loaded=np.linalg.norm(force[:3])>1e-4 or c.dist<0.
        if other==query.board:
            board_force+=world
            mujoco.mj_jac(m,d,jac,None,c.pos,int(m.geom_bodyid[ids[objslot]]))
            mujoco.mj_jac(m,d,other_jac,None,c.pos,int(m.geom_bodyid[other]))
            approach=max(approach,float(np.linalg.norm((jac-other_jac)@velocity)))
        elif query.roles[other]=="hand":
            side="left" if "left" in query.names[other] else "right"
            hands[side]+=int(loaded);hand_force+=world
        else:
            other_load+=float(np.linalg.norm(world))
    fp=query.footprint()
    mass=query.object_weight/np.linalg.norm(m.opt.gravity)
    residual=force_total+mass*m.opt.gravity
    return dict(time=float(d.time if time is None else time),force_semantics=force_semantics,
        dt=float(m.opt.timestep),contacts=contacts,bottom_margin=fp["bottom_margin"],com_margin=fp["com_margin"],
        board_vertical_load=float(board_force[2]),force_norm=float(np.linalg.norm(board_force)),
        approach_speed=approach,weight=query.object_weight,force_residual=float(np.linalg.norm(residual)),
        other_support_load=other_load,hand_contacts=sum(hands.values()),hand_contacts_by_side=hands,
        hand_vertical_load=float(hand_force[2]),object_linear=float(np.linalg.norm(velocity[49:52])),
        object_angular=float(np.linalg.norm(velocity[52:55])))


def foot_side(query, geom):
    body = int(query.m.geom_bodyid[geom])
    sides = [s for s,b in query.feet.items() if b == body]
    if len(sides) != 1:
        raise ValueError("unmapped_foot_contact_body")
    return sides[0]


class IntegratedEvidence:
    """Capture pre-step geometry/velocity and the force used by that same step.

    Call prepare after mj_step1 and finish immediately after mj_step2, before
    any forward/kinematics query on the live MjData. The solver contacts and
    Jacobians then refer to the saved pre-step geometry, not the new qpos.
    """
    def __init__(self, query, data):
        self.query = query
        self.data = data
        self.pending = None

    def prepare(self):
        if self.pending is not None:
            raise RuntimeError("unfinished_integrated_sample")
        self.pending = (float(self.data.time), self.data.qvel.copy())

    def finish(self):
        import mujoco
        if self.pending is None:
            raise RuntimeError("integrated_sample_not_prepared")
        t, velocity = self.pending
        self.pending = None
        q, d = self.query, self.data
        if abs(d.time-t-q.m.opt.timestep) > 1e-9:
            raise RuntimeError("integrated_sample_wrong_step")
        original = q.d
        q.d = d
        try:
            row = object_contact_evidence(q, force_semantics="integrated_step_world_force", time=t, velocity=velocity)
            load = {s:0. for s in ("left","right")}
            speed = dict(load)
            post_speed = dict(load)
            jac = np.zeros((3,q.m.nv))
            for i, contact in enumerate(d.contact):
                ids = (contact.geom1,contact.geom2)
                roles = [q.roles[g] for g in ids]
                if set(roles) != {"foot","floor"}:
                    continue
                foot = ids[roles.index("foot")]
                side = foot_side(q,foot)
                force = np.zeros(6)
                mujoco.mj_contactForce(q.m,d,i,force)
                load[side] += max(0.,float(force[0]))
                if force[0] > 1.:
                    mujoco.mj_jac(q.m,d,jac,None,contact.pos,int(q.m.geom_bodyid[foot]))
                    speed[side] = max(speed[side],float(np.linalg.norm((jac@velocity)[:2])))
                    post_speed[side] = max(post_speed[side],float(np.linalg.norm((jac@d.qvel)[:2])))
            row.update(foot_load=load,foot_slip=speed,foot_post_velocity_at_pre_geometry=post_speed,
                       force_pose_time=t,velocity_time=t,integrated_to=float(d.time))
            return row
        finally:
            q.d = original


def asset_inventory(query, source_binding, floor_bounds):
    """Record assumptions separately from verified source/model geometry."""
    m=query.m
    bounds=np.asarray(floor_bounds)
    if bounds.shape!=(2,3) or not np.isfinite(bounds).all():
        raise ValueError("invalid_floor_bounds")
    bodies=[dict(name=m.body(b).name,mass=float(m.body_mass[b]),inertia=m.body_inertia[b].tolist(),
                 com_local=m.body_ipos[b].tolist()) for b in query.object_bodies]
    return dict(schema="physical-asset-inventory/v2",source_binding=source_binding,
        object_bodies=bodies,object_weight=query.object_weight,floor_bounds=bounds.tolist(),
        collisions=[dict(name=query.names[g],type=int(m.geom_type[g]),size=m.geom_size[g].tolist(),
                         friction=m.geom_friction[g].tolist(),solref=m.geom_solref[g].tolist(),
                         solimp=m.geom_solimp[g].tolist()) for g in query.active],
        timestep=float(m.opt.timestep),solver=int(m.opt.solver),iterations=int(m.opt.iterations),
        calibration=dict(mass="uniform_scaling_hypothesis",inertia="uniform_scaling_hypothesis",
                         friction="source_model_not_measured",solver_sensitivity="not_verified"),
        physical_fidelity_verified=False)


def visual_visibility(frames, critical_phases, max_occlusion_seconds, dt=.04):
    """Consume renderer segmentation masks; nonblack RGB cannot substitute."""
    longest=run=0;seen=set();missing=[]
    for i,f in enumerate(frames):
        if f.get("phase") not in critical_phases:
            run=0;continue
        seen.add(f["phase"])
        counts=f.get("visible_pixels",{})
        visible=all(isinstance(counts.get(k),int) and counts[k]>0 for k in ("object","hands","support"))
        if not visible:missing.append(i)
        run=0 if visible else run+1
        longest=max(longest,run)
    checks=dict(all_phases_observed=set(critical_phases)<=seen,
                occlusion=longest*dt<=max_occlusion_seconds,
                frames_available=bool(frames))
    return dict(passed=all(checks.values()),checks=checks,longest_occlusion_seconds=longest*dt,
                missing_information_frames=missing)
