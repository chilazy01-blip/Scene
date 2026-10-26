"""Prepare task-relative six-dimensional palm keyframes, then fit one continuous reference.

The source root, legs, object trajectory, finger goals and original conditions
stay fixed. This is a Cartesian initialization experiment, not a stand-site
planner or a physical-success certificate.
"""
import time
import numpy as np
import mujoco
from scipy import sparse
from scipy.spatial.transform import Rotation
from scipy.sparse.linalg import lsqr
from sage.experiments.embodied_task_space_v6.certified_local_qp_r1 import solve_qp
from sage.experiments.embodied_task_space_v6.independent_qp_certificate_r1 import certify


def prepare(compiler, nominal_sources, nominal_residual, initial, deadline,
            sample_stride=40, ik_iterations=30):
    c, mapping = compiler.c, compiler.map
    reference, progress, velocity, acceleration = mapping.values(initial)
    active = compiler.active
    qadr, dadr = compiler.qadr, compiler.dadr
    movable = np.flatnonzero(~compiler.hand)
    palms = [c.m.geom('gripper0_' + side + '_g0_col').id for side in ('left', 'right')]
    chosen = sorted(set(range(0, mapping.n, sample_stride)) |
                    {int(t) for boundary in mapping.offsets[1:] for t in range(int(boundary)-25, int(boundary))})
    corrections = np.zeros_like(reference)
    measured = []
    def locations(q):
        c.d.qpos[:] = q
        mujoco.mj_kinematics(c.m, c.d)
        mujoco.mj_comPos(c.m, c.d)
        return np.array([c.d.geom_xpos[g].copy() for g in palms])
    for tick in chosen:
        if time.monotonic() >= deadline - 70:
            raise TimeoutError('task_relative_seed_preparation_deadline')
        phase = int(compiler.phase_of[tick])
        q, goals, hands = compiler.sources[phase].at(progress[tick])
        nq, ng, nh = nominal_sources[phase].at(progress[tick])
        nq[qadr] = reference[tick] + nominal_residual
        nominal_palms = locations(nq)
        nominal_orientations = np.array([c.d.geom_xmat[g].reshape(3,3).copy() for g in palms])
        old_rotation = np.empty(9);new_rotation = np.empty(9)
        # Both free-joint object quaternions are part of the frozen source data.
        mujoco.mju_quat2Mat(old_rotation, nq[53:57])
        mujoco.mju_quat2Mat(new_rotation, q[53:57])
        rotation = new_rotation.reshape(3,3) @ old_rotation.reshape(3,3).T
        targets = goals + (rotation @ (nominal_palms-ng).T).T
        endpoint = tick >= mapping.offsets[phase+1] - 25
        orientation_targets = np.array([rotation @ value for value in nominal_orientations])
        q[qadr] = reference[tick] + compiler.residual
        initial_error = float(np.linalg.norm(locations(q)-targets,axis=1).max())
        def rotation_errors():
            return np.array([Rotation.from_matrix(target @ c.d.geom_xmat[gid].reshape(3,3).T).as_rotvec() for gid,target in zip(palms,orientation_targets)])
        initial_angle = float(np.linalg.norm(rotation_errors(),axis=1).max())
        converged = False
        for iteration in range(ik_iterations):
            actual = locations(q)
            translation_error = targets-actual
            angles = rotation_errors()
            error = np.concatenate([np.r_[translation_error[k],.10*angles[k]] for k in range(2)])
            if np.linalg.norm(translation_error,axis=1).max() <= .0005 and np.linalg.norm(angles,axis=1).max() <= .005:
                converged = True;break
            jacobians=[]
            for gid in palms:
                jp=np.zeros((3,c.m.nv));jr=np.zeros_like(jp);mujoco.mj_jacGeom(c.m,c.d,jp,jr,gid)
                jacobians.append(np.vstack([jp[:,dadr[movable]],.10*jr[:,dadr[movable]]]))
            J=np.vstack(jacobians)
            delta=J.T@np.linalg.solve(J@J.T+1e-6*np.eye(12),error)
            scale=min(1.,.05/max(float(abs(delta).max()),1e-15))
            candidate=q[qadr[movable]]+delta*scale
            q[qadr[movable]]=np.clip(candidate,compiler.lower[movable]+compiler.residual[movable],compiler.upper[movable]+compiler.residual[movable])
        final_error=float(np.linalg.norm(locations(q)-targets,axis=1).max())
        final_angle=float(np.linalg.norm(rotation_errors(),axis=1).max())
        converged=final_error<=.0005 and final_angle<=.005
        corrections[tick]=q[qadr]-compiler.residual-reference[tick]
        measured.append(dict(tick=tick,phase=phase,endpoint=bool(endpoint),initial_error_m=initial_error,final_error_m=final_error,initial_orientation_error_rad=initial_angle,final_orientation_error_rad=final_angle,iterations=iteration+1,converged=converged))
    # Interpolate task-relative corrections only; one global spline fit retains
    # shared phase endpoints. The following certified projection restores all
    # original hard speed, acceleration, progress and stopping-reserve rows.
    for joint in range(mapping.j):
        corrections[:,joint]=np.interp(np.arange(mapping.n),chosen,corrections[chosen,joint])
    correction_fit=lsqr(mapping.Q,corrections.ravel(),atol=1e-10,btol=1e-10,iter_lim=500)
    desired=initial+correction_fit[0]
    seconds=min(60.,deadline-time.monotonic()-10)
    if seconds<=1:raise TimeoutError('task_relative_projection_deadline')
    diagonal=np.ones(mapping.size)
    # The certified backend requires explicit identity rows last. Restrict the
    # new initialization to +/- 1 rad of the original coefficients and retain
    # every original hard row. Keep the source clock and finger coefficients
    # exactly at the original reference: only arm keyframes are adapted here.
    lower=initial-1.;upper=initial+1.
    hand_rows=np.flatnonzero(np.tile(compiler.hand,mapping.n))
    fixed=np.unique(np.r_[mapping.Q[hand_rows].indices,np.arange(mapping.qvars,mapping.size)])
    lower[fixed]=initial[fixed];upper[fixed]=initial[fixed]
    # Keep the computed terminal IK poses during initialization projection.
    # These extra equalities belong only to this reference preparation; the
    # subsequent whole-path search retains its original task-space gates.
    terminal_ticks=np.asarray(mapping.offsets[1:]-1,dtype=int)
    terminal_reference=reference[terminal_ticks]+corrections[terminal_ticks]
    endpoint_rows=sparse.vstack([mapping.Q[t*mapping.j:(t+1)*mapping.j] for t in terminal_ticks],format='csr')
    endpoint_rhs=(terminal_reference-mapping.q0.reshape(mapping.n,mapping.j)[terminal_ticks]).ravel()
    matrix=sparse.vstack([mapping.hard,endpoint_rows,sparse.eye(mapping.size)],format='csr')
    low=np.r_[mapping.low,endpoint_rhs,lower];high=np.r_[mapping.high,endpoint_rhs,upper]
    if np.array_equal(desired,initial) and np.max(np.r_[low-matrix@initial,matrix@initial-high],initial=0.)<=2e-8:
        primal=initial.copy();dual=np.zeros(matrix.shape[0])
        info=dict(passed=True,status_code=0,status='exact unconstrained objective minimum also satisfies all original hard rows',solver_calls=0)
    else:
        primal,dual,info=solve_qp(diagonal,-desired,matrix,low,high,seconds)
        info['solver_calls']=1
    certificate=certify(diagonal,-desired,matrix,low,high,primal,dual,info.get('status_code')==0) if primal is not None else dict(passed=False)
    arrays=None
    if certificate['passed']:
        r,p,v,a=mapping.values(primal)
        arrays=dict(variables=primal,raw_reference=r,progress=p,raw_velocity=v,raw_acceleration=a,offsets=mapping.offsets)
    return dict(passed=bool(certificate['passed']),ik_keyframes=measured,ik_converged=sum(x['converged'] for x in measured),ik_total=len(measured),fit_stop_code=int(correction_fit[1]),fit_iterations=int(correction_fit[2]),fit_residual=float(correction_fit[3]),projection=info,independent_certificate=certificate,new_complete_robot_paths_evaluated=0,source_root_and_object_unchanged=True,source_clock_and_fingers_fixed=True,terminal_ik_poses_fixed_during_projection=True,object_relative_palm_orientation=True,stand_site_replanned=False,physics_steps=0,policy_forwards=0),arrays,dict(desired=desired,primal=np.array([]) if primal is None else primal,dual=np.array([]) if dual is None else dual,diagonal=diagonal,objective=-desired,low=low,high=high,fixed=fixed,initial=initial,corrections=corrections,terminal_ticks=terminal_ticks,terminal_reference=terminal_reference)
