"""Deterministic support-aware stance selection and planar reference routing."""
import heapq
import math
import numpy as np


def route(source=(.45,0.), target=(1.05,0.), spacing=.05):
    # Table half footprint .15/.18, robot/planning margin .24/.30.
    # This broad-phase envelope is checked again using complete native geometry.
    obstacles=[(x-.39,x+.39,y-.48,y+.48) for x,y in [source,target]]
    def free(node):
        x,y=np.array(node)*spacing
        return (-.2<=x<=1.65 and -.85<=y<=.85 and
                not any(a<=x<=b and c<=y<=d for a,b,c,d in obstacles))
    start=(0,0);candidates=[]
    for yaw in [0.,math.pi/2,-math.pi/2,math.pi]:
        xy=np.array(target)-.50*np.array([math.cos(yaw),math.sin(yaw)])
        goal=tuple(np.rint(xy/spacing).astype(int))
        if not free(goal):
            candidates.append(dict(yaw=yaw,goal=xy.tolist(),rejected='inflated_support_footprint'));continue
        queue=[(0,0,start)];cost={start:0};parent={};found=False
        while queue:
            _,g,node=heapq.heappop(queue)
            if g!=cost.get(node):continue
            if node==goal:found=True;break
            for dx,dy in [(0,-1),(1,0),(0,1),(-1,0)]:
                nxt=(node[0]+dx,node[1]+dy)
                if not free(nxt):continue
                ng=g+1
                if ng<cost.get(nxt,1e9):
                    cost[nxt]=ng;parent[nxt]=node
                    heapq.heappush(queue,(ng+abs(nxt[0]-goal[0])+abs(nxt[1]-goal[1]),ng,nxt))
        if not found:candidates.append(dict(yaw=yaw,rejected='no_route'));continue
        nodes=[goal]
        while nodes[-1]!=start:nodes.append(parent[nodes[-1]])
        points=np.asarray(nodes[::-1])*spacing
        headings=np.linspace(0,yaw,len(points));times=[0.]
        for i in range(1,len(points)):
            middle=(headings[i]+headings[i-1])/2
            rot=np.array([[math.cos(middle),math.sin(middle)],[-math.sin(middle),math.cos(middle)]])
            body_delta=rot@(points[i]-points[i-1])
            duration=max(abs(body_delta[0])/.15,abs(body_delta[1])/.08,abs(headings[i]-headings[i-1])/.15,.02)
            times.append(times[-1]+duration)
        candidates.append(dict(yaw=yaw,goal=xy.tolist(),points=points.tolist(),headings=headings.tolist(),times=times,duration_seconds=times[-1]))
    valid=[v for v in candidates if 'points' in v]
    if not valid:raise ValueError('no_collision_free_target_stance')
    selected=min(valid,key=lambda v:v['duration_seconds'])
    return dict(selected=selected,candidates=candidates,obstacles=obstacles,
                body_velocity_limits=[.15,.08,.15],broad_phase_only=True)


def at_time(route,t):
    s=route['selected'];times=s['times'];points=np.asarray(s['points']);headings=s['headings']
    return np.array([np.interp(t,times,points[:,0]),np.interp(t,times,points[:,1]),np.interp(t,times,headings)])
