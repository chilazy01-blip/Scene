"""Source-mesh free-space checks for objects explicitly placed under furniture."""
from pathlib import Path
import math
import numpy as np


def triangles_in_box(triangles, lower, upper):
    """Triangle/AABB separating-axis test; catches crossing faces without vertices inside."""
    center=(lower+upper)/2;half=(upper-lower)/2
    candidates=np.all(triangles.max(axis=1)>=lower,axis=1)&np.all(triangles.min(axis=1)<=upper,axis=1)
    selected=triangles[candidates]-center
    if not len(selected):return 0
    edges=np.roll(selected,-1,axis=1)-selected
    axes=[np.cross(edges[:,0],edges[:,1])]
    for edge in range(3):
        for axis in np.eye(3):axes.append(np.cross(edges[:,edge],axis))
    intersects=np.ones(len(selected),dtype=bool)
    for axis in axes:
        projections=np.einsum('nvi,ni->nv',selected,axis)
        radius=np.abs(axis)@half
        intersects &= (projections.min(axis=1)<=radius+1e-10)&(projections.max(axis=1)>=-radius-1e-10)
    return int(intersects.sum())


def audit_furnishing_geometry(scene, plan):
    from .p021_physics import _read_glb, _geometry, _bound
    links=[o for o in plan['objects'] if o.get('furnishing_attachment',{}).get('mode')=='under']
    if not links:return {'ok':True,'checks':[]}
    document,_=_read_glb(Path(scene))
    identifiers={n.get('extras',{}).get('scene_object_id') for n in document['nodes']}-{None}
    groups,_=_geometry(Path(scene),{'room':plan['room'],'objects':[{'id':i} for i in identifiers]})
    checks=[]
    for obj in links:
        parent=obj['furnishing_attachment']['parent_id'];angle=math.radians(obj.get('yaw',0))
        rotation=np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1]])
        points=np.concatenate([p['vertices'] for p in groups[obj['id']]])@rotation
        lower,upper=points.min(axis=0),points.max(axis=0)
        # Four millimetres of clearance around the actual object envelope.
        lower-=.004;upper+=.004
        triangles=np.concatenate([(p['vertices']@rotation)[p['faces']] for p in groups[parent]])
        count=triangles_in_box(triangles,lower,upper)
        checks.append({'object_id':obj['id'],'parent_id':parent,'method':'source_triangles_vs_actual_child_oriented_envelope_SAT',
                       'clearance_m':.004,'intersecting_parent_triangles':count,'ok':count==0})
    return {'schema':'scene-furnishing-geometry/v1','scene':_bound(Path(scene)),
            'ok':all(c['ok'] for c in checks),'checks':checks,
            'scope':'surface-intersection exclusion within actual child envelope; not a watertight-solid containment certificate'}
