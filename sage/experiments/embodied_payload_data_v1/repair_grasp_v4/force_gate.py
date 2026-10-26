"""Numerically qualified diagnostic force envelope; never production acceptance."""
from collections import deque
import math
from .intent import GraspRejected


class DiagnosticForceEnvelope:
    def __init__(self,report):
        if report.get('passed') is not True or report.get('production_calibrated') is not False:
            raise GraspRejected('force_numerical_admission_required')
        self.limits=report['proposed_diagnostic_limits']
        for side in ('left','right'):
            for key in ('peak_normal_N','maximum_40ms_impulse_Ns'):
                value=self.limits[side][key]
                if not math.isfinite(value) or value<=0:raise GraspRejected('invalid_force_envelope')
        self.dt=report.get('candidate_timestep',.005)
        if self.dt not in (.005,.0025):raise GraspRejected('unknown_force_timestep')
        self.window_steps=round(.04/self.dt)
        self.rows=deque(maxlen=self.window_steps);self.last_time=None;self.passed=False
        self.production_eligible=False

    def observe(self,row):
        if row.get('force_semantics')!='integrated_step_world_force' or abs(row.get('dt',0)-self.dt)>1e-10:
            raise GraspRejected('qualified_integrated_force_required')
        stamp=row.get('time',float('nan'))
        if not math.isfinite(stamp) or self.last_time is not None and abs(stamp-self.last_time-self.dt)>1e-8:
            raise GraspRejected('stale_force_observation')
        normal={s:row['hand_forces'][s]['normal_force'] for s in ('left','right')}
        if any(not math.isfinite(v) or v<0 for v in normal.values()):raise GraspRejected('invalid_normal_force')
        self.last_time=stamp;self.rows.append(normal)
        for side in normal:
            if normal[side]>self.limits[side]['peak_normal_N'] or sum(r[side]*self.dt for r in self.rows)>self.limits[side]['maximum_40ms_impulse_Ns']:
                raise GraspRejected('diagnostic_hand_force_envelope:'+side)
        self.passed=len(self.rows)==self.window_steps
        return self.passed
