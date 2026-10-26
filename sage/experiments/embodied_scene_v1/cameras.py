"""Explicit optical-frame correction for the upstream Stretch RGB-D cameras."""
import numpy as np
from scipy.spatial.transform import Rotation


def canonicalize_stretch_cameras(model):
    """Keep optical centers/forward axes; rotate image right/up axes by -90 deg.

    The imported Menagerie camera renders gravity horizontally in this model.
    This is a derived optical convention, not a claim of real calibration.
    Call once on a newly loaded model. Physics and actuators are untouched.
    """
    rows=[]
    for name in ('camera_rgb','camera_depth'):
        try:camera=model.camera(name)
        except KeyError:continue
        i=camera.id;original=model.cam_quat[i].copy()
        r=Rotation.from_quat(original[[1,2,3,0]]) * Rotation.from_euler('z',-90,degrees=True)
        model.cam_quat[i]=r.as_quat()[[3,0,1,2]]
        rows.append(dict(camera=name,source_quaternion_wxyz=original.tolist(),derived_quaternion_wxyz=model.cam_quat[i].tolist(),local_optical_roll_degrees=-90))
    return rows
