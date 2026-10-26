"""Translate coordinator output to the already admitted 50 Hz native interface.

Validation alone performs no policy inference. Task/contact observations must
come from an actual native rollout before this adapter can confer task evidence.
"""
def packet(command, reference):
    return dict(tick=command['tick'],dt=.02,frame=command['frame'],units=command['units'],
                navigate=list(command['nav']),height=command['height'],rpy=list(command['rpy']),
                q_reference=list(reference))
