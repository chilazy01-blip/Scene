"""Deterministic admission of an axis-aligned generated support, no tuning."""
from pathlib import Path
import json,xml.etree.ElementTree as ET
from .scene import attach_generated_room


def plan_support_task(package):
    task=json.loads((Path(package)/'task.json').read_text());pose=task['support_pose'];lo,hi=task['support_bounds_local_m']
    if any(abs(pose[i][j]-(1 if i==j else 0))>1e-8 for i in range(3) for j in range(3)):raise ValueError('rotated_support_not_supported')
    # Place and carry in a left/front region; the source book remains untouched.
    half=[.02,.04,.04];carry=.12;margin=.05;local=[lo[0]+half[0]+margin+carry,-.12]
    if not (lo[1]+half[1]+margin<=local[1]<=hi[1]-half[1]-margin):raise ValueError('insufficient_support_depth')
    if local[0]+half[0]+margin>hi[0]:raise ValueError('insufficient_support_width')
    world=[pose[0][3]+local[0],pose[1][3]+local[1]];origin=[world[0]-.02,world[1]-.64];surface=pose[2][3]+hi[2]
    return dict(source_package=str(Path(package).resolve()),support_bounds=task['support_bounds_local_m'],support_pose=pose,pick_world_xy=world,origin=origin,surface_z=surface,home_lift=min(.85,surface+.12),half_size=half,carry_m=carry,edge_margin_m=margin,scope='new calibration box on a previously unused generated support; original book and all source bodies retained; not a new independently generated room')


def attach_support_task(robot_xml,plan,output):
    info=attach_generated_room(robot_xml,plan['source_package'],output,origin=plan['origin'])
    root=ET.parse(output).getroot();root.find("worldbody/body[@name='task_object']").set('pos',f"-.02 -.64 {plan['surface_z']+plan['half_size'][2]+.0002}");ET.indent(root);Path(output).write_text(ET.tostring(root,encoding='unicode'))
    info['task_scope']=plan['scope'];info['support_task_plan']=plan
    return info


def support_polygon(points,center,height_tolerance=.0005,min_margin=.005):
    """Conservative sampled quasi-static support; dynamic gates still required.

    Points must be inside the actual footprint, not an inflated clearance box.
    Lower pockets are allowed; high contact points must contain the COM.
    """
    import numpy as np
    p=np.asarray(points,dtype=float);center=np.asarray(center,dtype=float)
    if p.ndim!=2 or p.shape[1]!=3 or not np.isfinite(p).all():return dict(passed=False,reason='invalid_samples')
    top=float(p[:,2].max());xy=sorted(set(map(tuple,p[p[:,2]>=top-height_tolerance,:2])))
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower=[];upper=[]
    for point in xy:
        while len(lower)>=2 and cross(lower[-2],lower[-1],point)<=0:lower.pop()
        lower.append(point)
    for point in reversed(xy):
        while len(upper)>=2 and cross(upper[-2],upper[-1],point)<=0:upper.pop()
        upper.append(point)
    hull=lower[:-1]+upper[:-1]
    if len(hull)<3:return dict(passed=False,reason='no_support_area',surface_z=top)
    margin=min(cross(a,b,center)/float(np.linalg.norm(np.array(b)-a)) for a,b in zip(hull,hull[1:]+hull[:1]));span=float(np.ptp(p[:,2]))
    return dict(passed=bool(margin>=min_margin and span<=.005),surface_z=top,support_hull=[list(x) for x in hull],com_margin_m=float(margin),sample_height_span_m=span,top_sample_count=len(xy),assumption='sampled static support only, actual simulation quality gates required')
