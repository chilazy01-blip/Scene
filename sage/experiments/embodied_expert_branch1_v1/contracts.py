"""Observable phase contracts; diagnostics never replace the frozen native judge.

Times are physical seconds, positions metres, rotations object-local to world.
A policy tick has four 200 Hz physics samples. `up` belongs to the robot root.
"""
import math

LOADED = frozenset(('lift','loaded_hover','tuck','carry','target_stop','place'))
CONTRACTS = {
 'close': {'pre': 'Admitted mesh approach completed', 'invariant': 'Native plant and reference envelope remain fixed', 'post': 'Measured opposing contacts before load probe'},
 'load_probe': {'pre': 'Opposing contacts acquired', 'invariant': 'Original anchor/slip and safety gates', 'post': 'Measured load probe passes; save acquired reference'},
 'lift': {'pre': 'Load probe passed', 'invariant': 'Retain grasp while table support disappears', 'post': 'Clearance and continuous hover'},
 'loaded_hover': {'pre': 'Object clear of table', 'invariant': 'Retain acquired grasp', 'post': 'Measured hover interval passes'},
 'tuck': {'pre': 'Hover passed', 'invariant': 'Continue acquired grasp across callback transition', 'post': 'Carry reference ready'},
 'carry': {'pre': 'Object held off table', 'invariant': 'Measured grasp retained; no hand support on furniture', 'post': 'Original distance and both-foot cycles'},
 'target_stop': {'pre': 'Carry completed', 'invariant': 'Retain grasp while root stops', 'post': 'Target stop reached'},
 'place': {'pre': 'Carry/stop completed with held object', 'invariant': 'Retain grasp until measured target table handoff', 'post': 'Measured support transfer before release'},
 'release': {'pre': 'Measured target table support', 'invariant': 'Object supported as fingers open', 'post': 'Hand contact clears'},
 'settle': {'pre': 'Released/retracted', 'invariant': 'Full last 200 physics samples supported, no hand contact, object speed <.02, root speed <.06', 'post': 'Original gates plus object orientation >=.98'},
}


def observe(sample, case):
    R = sample['object_rotation']
    axis = case.get('orientation_axis', [0., 0., 1.])
    # Full matrix is row-major; use world-Z dot the declared local axis.
    if len(R) == 9:
        R = [R[0:3], R[3:6], R[6:9]]
    cosine = sum(float(R[2][i])*float(axis[i]) for i in range(3))
    if case['object_id'] == 'book': cosine = abs(cosine)
    stage = sample['stage']
    airborne = not sample['desk_supported']
    diagnostics = []
    if not sample['safe']: diagnostics.append('original_physical_gate_rejection')
    if stage in LOADED and airborne and not sample['hand_contact']:
        diagnostics.append('airborne_grasp_contact_absent')
    if stage == 'release' and airborne: diagnostics.append('release_without_measured_table_support')
    return dict(tick=sample['tick'], time_s=sample['time_after_s'], phase=stage,
                robot_root_up_cosine=sample['up'], object_orientation_cosine=cosine,
                object_orientation_margin=cosine-.98, desk_supported=sample['desk_supported'],
                hand_contact=sample['hand_contact'], forces_n=sample['forces'],
                object_world_m=sample['object_m'], object_in_root_m=sample['object_local_m'],
                diagnostic_breaches=diagnostics)
