"""Apply one explicit robot mount and camera contract; no task-dependent search."""
import numpy as np
from sage.experiments.embodied_scene_v1.package import vec


def apply_fixed_scene(root, task, contract):
    mount = contract['robot_mount']
    xyz = np.asarray(mount['position_m'])
    root.find("worldbody/body[@name='base']").set('pos', vec(xyz))
    root.find("worldbody/body[@name='base']").set('quat', vec(mount['quaternion_wxyz']))
    root.find("worldbody/geom[@name='robot_mount']").set('pos', vec(xyz-[0,0,.01]))
    for item in contract['cameras'].values():
        camera = root.find(f".//camera[@name='{item['model_camera']}']")
        if camera is None:
            raise ValueError('fixed_camera_missing:'+item['model_camera'])
        for key in ['xyaxes','zaxis','axisangle','euler']:
            camera.attrib.pop(key,None)
        camera.set('pos',vec(item['local_position_m']))
        camera.set('quat',vec(item['local_quaternion_wxyz']))
        camera.set('fovy',str(item['fovy_degrees']))
    selected = dict(position_m=xyz.tolist(), quaternion_wxyz=mount['quaternion_wxyz'],
                    status='explicit_fixed_mount_pending_preflight', index=None)
    return dict(selected=selected,candidates=[selected],budget=1,scene_edits=0,
                per_configuration_mount_search=False,
                interpretation='Same externally frozen mounting and cameras; no feasibility claim yet')
