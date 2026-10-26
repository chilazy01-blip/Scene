"""Exercise the actual request adapter and transition over stop and reversal."""
import types,numpy as np
from .work import E,c,finish
from .velocity_transition import VelocityTransition
from .velocity_request_adapter import ATTRIBUTES,call_with_issued_velocity


def main():
    ctrl=types.SimpleNamespace(lin_vel_x=0.,lin_vel_y=0.,ang_vel_z=0.)
    transition=VelocityTransition([.2,.15,.3],[.25,.25,.5]);transition.issued[:]=[.17,-.0698287338,-.0032574418]
    rows=[]
    for i in range(40):
        requested=np.array([getattr(ctrl,a) for a in ATTRIBUTES]);issued=transition.command(requested)
        seen=call_with_issued_velocity(ctrl,issued,lambda q:np.array([getattr(q,a) for a in ATTRIBUTES]))
        assert np.array_equal(seen,issued)
        assert np.array_equal([getattr(ctrl,a) for a in ATTRIBUTES],requested)
        rows.append(seen.tolist())
    assert np.max(abs(transition.issued))<1e-14
    assert np.max(abs(np.diff(np.array([[.17,-.0698287338,-.0032574418],*rows]),axis=0))-np.array([.005,.005,.01]))<1e-14
    ctrl.lin_vel_x=-.4
    for _ in range(50):
        issued=transition.command([ctrl.lin_vel_x,ctrl.lin_vel_y,ctrl.ang_vel_z])
        call_with_issued_velocity(ctrl,issued,lambda q:q.lin_vel_x)
        assert ctrl.lin_vel_x==-.4
    assert abs(transition.issued[0]+.2)<1e-14
    def fail(q):raise ValueError('expected test exception')
    try:call_with_issued_velocity(ctrl,[.1,.1,.1],fail)
    except ValueError:pass
    else:raise AssertionError('callback exception was suppressed')
    assert ctrl.lin_vel_x==-.4 and ctrl.lin_vel_y==0. and ctrl.ang_vel_z==0.
    report={'passed':True,'zero_physics_steps':True,'actual_adapter_and_transition_checked':True,'saved_D3_nonzero_velocity_to_zero_seconds':.68,'stop_issued_history':rows,'navigation_requests_persist':True,'accelerations_and_speed_caps_preserved':True,'callback_exception_restores_requests':True,'production_accepted':False}
    c.write(E/'D_VELOCITY_REQUEST_SEMANTICS_PREFLIGHT.json',report);finish(report)


if __name__=='__main__':main()
