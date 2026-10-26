"""Bounded tabletop translation after asset dimensions change."""
from __future__ import annotations
from copy import deepcopy
import math


def _box(obj):
    d=obj['dimensions']; angle=math.radians(float(obj.get('yaw',0)))
    w=abs(math.cos(angle))*d['width']+abs(math.sin(angle))*d['length']
    l=abs(math.sin(angle))*d['width']+abs(math.cos(angle))*d['length']
    return obj['x']-w/2,obj['y']-l/2,obj['x']+w/2,obj['y']+l/2


def repair_support_footprints(plan, step=.005, margin=.008):
    """Translate only conflicted siblings; defer true surface support to GLB QA."""
    from .validator import validate_layout
    findings=validate_layout(plan)['violations']
    affected=set()
    for finding in findings:
        if finding['type']=='support_containment':affected.add(finding['object_id'])
        elif finding['type']=='support_object_collision':affected.update(finding['objects'])
    byid={o['id']:o for o in plan['objects']}; changes=[]; unresolved=[]
    groups={}
    for obj in plan['objects']:
        request=obj.get('support_surface_request') or {}
        if request.get('surface')=='seat':continue
        parent=request.get('parent') or obj.get('support_id') or obj.get('container_id')
        if parent:
            groups.setdefault((parent,request.get('tier_from_bottom','top')),[]).append(obj)
    for (parent,tier),children in groups.items():
        if parent not in byid:continue
        for i,left in enumerate(children):
            a=_box(left)
            for right in children[i+1:]:
                b=_box(right)
                if not (a[2]+margin<=b[0] or b[2]+margin<=a[0] or a[3]+margin<=b[1] or b[3]+margin<=a[1]):
                    affected.update([left['id'],right['id']])
        bounds=_box(byid[parent]);placed=[]
        for obj in children:
            if obj['id'] not in affected:
                placed.append(obj)
                continue
            original=(obj['x'],obj['y']);box=_box(obj)
            halfw,halfl=(box[2]-box[0])/2,(box[3]-box[1])/2
            def valid(x,y):
                b=(x-halfw,y-halfl,x+halfw,y+halfl)
                if b[0]<bounds[0]+margin or b[1]<bounds[1]+margin or b[2]>bounds[2]-margin or b[3]>bounds[3]-margin:return False
                return all(b[2]+margin<=q[0] or q[2]+margin<=b[0] or b[3]+margin<=q[1] or q[3]+margin<=b[1] for q in map(_box,placed))
            if not valid(*original):
                xmin,ymin=bounds[0]+margin+halfw,bounds[1]+margin+halfl
                xmax,ymax=bounds[2]-margin-halfw,bounds[3]-margin-halfl
                candidates=[]
                if xmin<=xmax and ymin<=ymax:
                    for i in range(int((xmax-xmin)/step)+1):
                        x=xmin+i*step
                        for j in range(int((ymax-ymin)/step)+1):
                            y=ymin+j*step
                            if valid(x,y):candidates.append(((x-original[0])**2+(y-original[1])**2,x,y))
                if candidates:
                    _,obj['x'],obj['y']=min(candidates)
                    changes.append(dict(object_id=obj['id'],parent=parent,previous_xy=list(original),xy=[obj['x'],obj['y']],reason='source_dimension_change_tabletop_footprint_repair'))
                else:unresolved.append(obj['id'])
            placed.append(obj)
    return dict(changes=changes,unresolved=unresolved,ok=not unresolved,scope='conservative 2D envelopes only; actual mesh support and intersections must be checked subsequently')


def repair_wall_trim_clearance(plan, trim_depth=.036, trim_height=.10, margin=.002):
    """Keep low wall-backed objects and their dependents in front of trim."""
    room=plan['room']; changes=[]
    for obj in plan['objects']:
        if obj.get('support_id') or obj.get('container_id') or obj.get('support_surface_request'):
            continue
        if float(obj.get('z',0))>=trim_height:continue
        wall=obj.get('preferred_wall');bounds=_box(obj);dx=dy=0.
        if wall=='west':dx=max(0.,trim_depth+margin-bounds[0])
        elif wall=='east':dx=min(0.,room['width']-trim_depth-margin-bounds[2])
        elif wall=='south':dy=max(0.,trim_depth+margin-bounds[1])
        elif wall=='north':dy=min(0.,room['length']-trim_depth-margin-bounds[3])
        if abs(dx)+abs(dy)<1e-9:continue
        moved={obj['id']}
        for _ in plan['objects']:
            before=len(moved)
            for child in plan['objects']:
                parent=child.get('support_id') or child.get('container_id') or child.get('support_surface_request',{}).get('parent')
                if parent in moved:moved.add(child['id'])
            if len(moved)==before:break
        for child in plan['objects']:
            if child['id'] in moved:child['x']+=dx;child['y']+=dy
        changes.append(dict(object_id=obj['id'],wall=wall,delta_xy=[dx,dy],translated_ids=sorted(moved),trim_depth_m=trim_depth,clearance_m=margin))
    return changes
