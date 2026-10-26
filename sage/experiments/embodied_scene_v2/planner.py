"""Frozen v1 occupancy A*, now driven by resolved task coordinates."""
from pathlib import Path
import heapq,json
import numpy as np

def occupancy_path(package, start_xyz, goal_xy, reference=False, radius=.38):
    if reference: return np.array([start_xyz[:2], goal_xy])
    objects = json.loads((Path(package)/'objects.json').read_text())
    pitch = .05; shape = (117, 101); grid = np.zeros(shape, dtype=bool)
    xx, yy = np.meshgrid(np.arange(shape[0])*pitch, np.arange(shape[1])*pitch, indexing='ij')
    grid |= (xx < radius) | (xx > 5.8-radius) | (yy < radius) | (yy > 5-radius)
    for name, obj in objects.items():
        if name in ('task_book', 'explicit_area_rug') or name.startswith('leaning_book'): continue
        pose = np.asarray(obj['pose_z_up']); ext = np.asarray(obj['dimensions_local_m'])
        if pose[2,3]-ext[2]/2 > 1.5: continue
        local = np.stack([xx-pose[0,3], yy-pose[1,3]], axis=-1) @ pose[:2,:2]
        delta = np.maximum(np.abs(local)-ext[:2]/2, 0)
        grid |= np.linalg.norm(delta, axis=-1) < radius
    start = tuple(np.rint(np.array(start_xyz[:2])/pitch).astype(int)); goal = tuple(np.rint(np.array(goal_xy)/pitch).astype(int))
    if grid[start] or grid[goal]: raise ValueError('Navigation start/goal violates declared clearance')
    todo = [(0, start)]; cost={start:0}; parent={}
    while todo:
        _, current=heapq.heappop(todo)
        if current==goal: break
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            n=(current[0]+dx,current[1]+dy)
            if not (0<=n[0]<shape[0] and 0<=n[1]<shape[1]) or grid[n]:continue
            if dx and dy and (grid[current[0]+dx,current[1]] or grid[current[0],current[1]+dy]):continue
            c=cost[current]+np.hypot(dx,dy)
            if c<cost.get(n, float('inf')):
                cost[n]=c;parent[n]=current;heapq.heappush(todo,(c+np.linalg.norm(np.array(n)-goal),n))
    if goal==start:return np.asarray([start_xyz[:2],goal_xy])
    if goal not in parent: raise ValueError('No collision-clear path')
    cells=[goal]
    while cells[-1]!=start:cells.append(parent[cells[-1]])
    return np.array(cells[::-1])*pitch

