"""Keep hand preload semantics separate from a free-space pose reference.

These components fail closed. They do not grant physical admission or replace
the planner's collision corridor, native actuator limits, or force calibration.
"""
from dataclasses import dataclass
import math


class GraspRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class HandIntent:
    mode: str
    command: tuple[float, ...]
    expected_pose: tuple[float, ...] | None = None

    def __post_init__(self):
        if not self.command or not all(math.isfinite(x) for x in self.command):
            raise ValueError('invalid_hand_command')
        if self.mode == 'position':
            if (self.expected_pose is None or len(self.expected_pose) != len(self.command)
                    or not all(math.isfinite(x) for x in self.expected_pose)
                    or any(abs(a-b) > 1e-10 for a,b in zip(self.command,self.expected_pose))):
                raise GraspRejected('position_command_reference_conflict')
        elif self.mode == 'contact_preload':
            if self.expected_pose is not None:
                raise GraspRejected('preload_cannot_require_demo_pose')
        else:
            raise ValueError('unknown_hand_intent')

    def integral_error(self, actual):
        """A preload may not be cancelled by historical-pose integral feedback.

        None is explicit: callers must freeze that channel's integral state,
        not substitute fabricated measured positions in the tracking evidence.
        Position-mode targets require a validated retimed reference/response.
        """
        if len(actual) != len(self.command) or not all(math.isfinite(x) for x in actual):
            raise ValueError('invalid_hand_observation')
        if self.mode == 'contact_preload':
            return None
        return tuple(a-b for a,b in zip(self.expected_pose,actual))


@dataclass(frozen=True)
class GraspLimits:
    dt: float = .02
    contact_dwell: float = .1
    max_closure_seconds: float = 2.
    test_lift_distance: float = .005
    transport_lift: float = .05
    relative_displacement: float = .02
    relative_speed: float = .03
    loaded_fraction: float = .8

    def __post_init__(self):
        if any(not math.isfinite(x) or x <= 0 for x in vars(self).values()):
            raise ValueError('invalid_grasp_limits')
        if not self.test_lift_distance < self.transport_lift or self.loaded_fraction > 1:
            raise ValueError('invalid_grasp_limits')


class GraspGate:
    """Authorize only a bounded lift probe before measured load transfer.

    Evidence must be fresh integrated observations. Bilateral touching alone
    permits at most a 5mm probe after dwell, never full transport. Full lift
    requires actual upward load transfer. A caller must still provide motion
    sweeps and a separately calibrated hand-force/impulse limit.
    """
    def __init__(self, limits=GraspLimits()):
        self.limits=limits
        self.last_time=None
        self.stable=self.elapsed=0.

    def observe(self, *, time, semantics, contacts, upward_load, weight,
                relative_displacement, relative_speed, lift, arm_tracking_ok,
                corridor_passed, force_limits_passed):
        values=(time,upward_load,weight,relative_displacement,relative_speed,lift)
        if not all(math.isfinite(x) for x in values) or weight <= 0:
            raise GraspRejected('invalid_grasp_evidence')
        if (set(contacts) != {'left','right'} or any(type(v) is not int or v < 0 for v in contacts.values())
                or relative_displacement < 0 or relative_speed < 0):
            raise GraspRejected('invalid_grasp_evidence')
        if semantics != 'integrated_step_world_force':
            raise GraspRejected('integrated_grasp_evidence_required')
        l=self.limits
        if self.last_time is not None and abs(time-self.last_time-l.dt)>1e-8:
            raise GraspRejected('stale_or_gapped_grasp_observation')
        self.last_time=time
        self.elapsed+=l.dt
        bilateral=all(contacts[s]>0 for s in ('left','right'))
        stable=(bilateral and relative_displacement<=l.relative_displacement
                and relative_speed<=l.relative_speed and arm_tracking_ok is True)
        self.stable=self.stable+l.dt if stable else 0.
        ready=self.stable+1e-12>=l.contact_dwell
        safe=corridor_passed is True and force_limits_passed is True
        loaded=upward_load>=l.loaded_fraction*weight
        probe=ready and safe and lift<=l.test_lift_distance
        full_lift=ready and safe and loaded
        transport=full_lift and lift>=l.transport_lift
        if not full_lift and self.elapsed>l.max_closure_seconds+1e-12:
            raise GraspRejected('grasp_load_transfer_timeout')
        return dict(bilateral=bilateral,stable=ready,loaded=loaded,
                    allow_probe=probe,probe_distance_limit=l.test_lift_distance,
                    allow_full_lift=full_lift,allow_transport=transport)
