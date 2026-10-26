"""Original bounded feedback and persistent height slew for a frozen path.

Pure command construction; no simulator state mutation, policy call or task
qualification. The caller must retain the returned height across every tick.
"""
import math


def body_command(base_xy,yaw,goal_xy,goal_yaw,desired_height,last_height):
    if len(base_xy)!=2 or len(goal_xy)!=2:raise ValueError('body_goal_dimensions')
    values=[*base_xy,yaw,*goal_xy,goal_yaw,desired_height,last_height]
    if not all(math.isfinite(float(v)) for v in values):raise ValueError('body_goal_finite')
    if not .64<=desired_height<=.74 or not .64<=last_height<=.74:raise ValueError('body_height_domain')
    dx,dy=[goal_xy[k]-base_xy[k] for k in range(2)];c,s=math.cos(yaw),math.sin(yaw);error=math.atan2(math.sin(goal_yaw-yaw),math.cos(goal_yaw-yaw))
    nav=[max(-.15,min(.15,1.5*(c*dx+s*dy))),max(-.08,min(.08,1.5*(-s*dx+c*dy))),max(-.15,min(.15,1.5*error))]
    height=last_height+max(-.0004,min(.0004,desired_height-last_height))
    return dict(navigate=nav,height=height,rpy=[0.,0.,0.])


class BodyHistory:
    def __init__(self):self.next_tick=0;self.height=.74
    def step(self,tick,base_xy,yaw,goal_xy,goal_yaw,desired_height):
        if type(tick) is not int or tick!=self.next_tick:raise ValueError('body_history_tick')
        result=body_command(base_xy,yaw,goal_xy,goal_yaw,desired_height,self.height)
        self.height=result['height'];self.next_tick+=1;return result
    def snapshot(self):return dict(next_tick=self.next_tick,height=self.height)
