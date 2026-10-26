"""Camera/appearance changes only; never advances physics or edits contact geometry."""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation

CAMERAS = {'workspace': 'workspace', 'wrist': 'eye_in_hand'}

def look_at(model, name, position, target):
    cid = model.camera(name).id
    z = np.asarray(position, float) - target
    z /= np.linalg.norm(z)
    x = np.cross([0., 0., 1.], z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    model.cam_pos[cid] = position
    model.cam_quat[cid] = Rotation.from_matrix(np.stack([x,y,z], axis=1)).as_quat()[[3,0,1,2]]

def configure(model, width=320, height=240, appearance='baseline', camera='training'):
    model.vis.global_.offwidth = width
    model.vis.global_.offheight = height
    if camera == 'training':
        look_at(model, 'workspace', [2.65, 2.12, 1.95], np.array([2.33,3.45,1.05]))
        model.cam_fovy[model.camera('workspace').id] = 48.
    if appearance == 'improved':
        model.vis.headlight.ambient[:] = [.28,.28,.28]
        model.vis.headlight.diffuse[:] = [.5,.5,.5]
        model.vis.headlight.specular[:] = [.08,.08,.08]
        model.light_ambient[:] = [.15,.15,.15]
        model.light_diffuse[:] = [.55,.53,.50]
        model.light_specular[:] = [.10,.10,.10]
        model.light_castshadow[:] = False
        model.mat_specular[:] = np.minimum(model.mat_specular, .18)
        model.mat_shininess[:] = np.minimum(model.mat_shininess, .25)
    for i in range(model.ngeom):
        if model.geom_bodyid[i] == 0 and model.geom_group[i] == 0:
            model.geom_group[i] = 2
    options = mujoco.MjvOption()
    options.geomgroup[:] = [0,1,1,0,0,0]
    options.sitegroup[:] = 0
    return options

def camera_contract(model, width, height):
    result = {}
    for key, name in CAMERAS.items():
        cid = model.camera(name).id
        focal = .5*height/np.tan(np.deg2rad(model.cam_fovy[cid])/2)
        result[key] = dict(model_camera=name, camera_id=cid,
            parent_body=model.body(int(model.cam_bodyid[cid])).name,
            local_position_m=model.cam_pos[cid].tolist(),
            local_quaternion_wxyz=model.cam_quat[cid].tolist(),
            fovy_degrees=float(model.cam_fovy[cid]),
            K=[[float(focal),0,width/2],[0,float(focal),height/2],[0,0,1]],
            camera_coordinates='MuJoCo OpenGL: +X right,+Y up,-Z forward',
            pixel_origin='top-left', resolution=[width,height])
    return result
