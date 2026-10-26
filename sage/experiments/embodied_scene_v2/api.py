"""Public request admission; frozen rollouts retain their original controller."""
import json
import numpy as np
from scipy.spatial.transform import Rotation
from .config import PACKAGE,validate

def validate_request(request):
    c=validate(request);objects=json.loads((PACKAGE/'objects.json').read_text())
    if c['task']=='pick_place':
        desk=np.asarray(c['object_poses'].get('explicit_desk',objects['explicit_desk']['pose_z_up']))
        desk_half=np.asarray(objects['explicit_desk']['dimensions_local_m'])/2
        book_half=np.asarray(objects['leaning_book_01']['dimensions_local_m'])/2
        rotation=Rotation.from_euler('z',c['start_yaw_rad']).as_matrix()
        corners=np.array([[x,y,z] for x in [-book_half[0],book_half[0]] for y in [-book_half[1],book_half[1]] for z in [-book_half[2],book_half[2]]])
        for key in ['start','goal']:
            world=corners@rotation.T+c[key];local=(world-desk[:3,3])@desk[:3,:3]
            if np.any(abs(local[:,:2])>desk_half[:2]+1e-5):raise ValueError('Target '+key+' footprint leaves designated tabletop')
            gap=float(local[:,2].min()-desk_half[2])
            if not -.001<=gap<=.05:raise ValueError('Target '+key+' has invalid support height')
    else:
        radius=.38;x,y=c['start'][:2]
        if not radius<=x<=5.8-radius or not radius<=y<=5-radius:raise ValueError('Robot start intersects room boundary')
    return c
