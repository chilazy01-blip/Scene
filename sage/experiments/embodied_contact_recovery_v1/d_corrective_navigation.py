"""D corrective stance movement without the source's mandatory retreat leg."""
import numpy as np
from .safe_approach_r3 import hand_bounds
from .velocity_transition import VelocityTransition


def install(p,config):
    import instrument
    original=p.corrective_leg
    def corrective(runner,base_xy,yaw):
        goal=np.asarray(base_xy,float);here=runner.data.qpos[:2].copy()
        error=abs(float(p.base.yaw_err_to(runner.data,yaw)))
        if np.linalg.norm(goal-here)>.50 or error>np.radians(30):
            return original(runner,goal,yaw)
        lo,_=hand_bounds(runner.model,runner.data)
        table=runner.model.geom('table_top').id
        top=runner.data.geom_xpos[table,2]+runner.model.geom_size[table,2]
        if lo[2]<top+.035:
            raise p.EpisodeAborted('D_corrective_actual_hand_clearance')
        # Use the same bounded command transition qualified during retained-arm
        # retreat. The route remains a development experiment until observed.
        runner.ctrl._D_velocity_transition=VelocityTransition(config['transport_velocity_cap'],config['transport_acceleration_cap'])
        tr=instrument.ACTIVE_TRACE;tr.append('D_corrective/physics_row',tr.n);tr.append('D_corrective/from_goal',np.r_[here,goal])
        started=float(runner.data.time)
        err=p.ep.walk_to(runner,goal,goal_yaw=yaw,timeout=20.)
        detail={'D_direct_corrective':True,'L':0.,'ahead':float((here-goal)@np.array([np.cos(yaw),np.sin(yaw)])),
                'retreat_err_m':0.,'retreat_s':0.,'retreat_along':0.,'return_err_m':float(err),
                'return_s':float(runner.data.time)-started,'return_len_m':float(np.linalg.norm(goal-here))}
        return float(err),detail
    p.corrective_leg=corrective
    return {'scope':'D measured small corrective stance, distance<=.5m and yaw error<=30deg','required_actual_hand_clearance_m':.035,'forced_retreat_removed':True,'plant_unchanged':True,'no_additional_replan_count':True}
