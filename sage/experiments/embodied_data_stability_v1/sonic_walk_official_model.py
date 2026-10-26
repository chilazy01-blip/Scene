"""Derive a body-only observer from the actual official MuJoCo scene model.

Unresolved mesh geometry is removed in memory. Fourteen hand joints are fixed
at zero while all hand bodies and inertias remain. Joint classes retain the
official 0.01 armature, 0.05 damping and class friction, without policy-derived
armature substitutions. This remains an explicitly collision-lite model.
"""

import hashlib
import xml.etree.ElementTree as ET

from .sonic_native_dynamic_shadow import DEFAULT_SOURCE
from .sonic_native_planner_preflight import _file_binding
from .sonic_shadow import SONIC_BODY_JOINT_ORDER

OFFICIAL_MODEL = (
    DEFAULT_SOURCE / "gear_sonic/data/robot_model/model_data/g1/g1_29dof_with_hand.xml"
)
OFFICIAL_SCENE = OFFICIAL_MODEL.with_name("scene_43dof.xml")


def official_body_model_xml():
    root = ET.parse(OFFICIAL_MODEL).getroot()
    removed_mesh_assets = removed_mesh_geoms = removed_joint_sensors = 0
    fixed_hand_joints = []
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "mesh":
                parent.remove(child)
                removed_mesh_assets += 1
            elif child.tag == "geom" and child.attrib.get("type") == "mesh":
                parent.remove(child)
                removed_mesh_geoms += 1
            elif (
                child.tag == "joint"
                and child.attrib.get("name")
                and child.attrib["name"]
                not in (*SONIC_BODY_JOINT_ORDER, "floating_base_joint")
            ):
                fixed_hand_joints.append(child.attrib["name"])
                parent.remove(child)
    actuators = root.find("actuator")
    aliases = {}
    for child in list(actuators):
        joint = child.attrib.get("joint")
        if joint not in SONIC_BODY_JOINT_ORDER:
            actuators.remove(child)
        else:
            aliases[child.attrib["name"]] = joint
            child.set("name", joint)
    sensors = root.find("sensor")
    for child in list(sensors):
        if child.attrib.get("joint") in fixed_hand_joints:
            sensors.remove(child)
            removed_joint_sensors += 1
        elif child.tag == "gyro" and child.attrib.get("name") == "imu_gyro":
            child.set("name", "imu-angular-velocity")
    world = root.find("worldbody")
    floor = ET.parse(OFFICIAL_SCENE).getroot().find("worldbody/geom[@name='floor']")
    floor.attrib.pop("material", None)
    floor.set("friction", "1.0 0.005 0.0001")
    world.append(floor)
    if len(fixed_hand_joints) != 14 or len(actuators) != 29:
        raise RuntimeError("official body/hand separation contract changed")
    payload = ET.tostring(root, encoding="utf-8")
    return payload, {
        "source": _file_binding(OFFICIAL_MODEL),
        "scene": _file_binding(OFFICIAL_SCENE),
        "mesh_assets_removed": removed_mesh_assets,
        "mesh_geometries_removed": removed_mesh_geoms,
        "fixed_hand_joints": fixed_hand_joints,
        "removed_hand_joint_sensors": removed_joint_sensors,
        "actuator_name_aliases_only": aliases,
        "preserved_official_joint_class_dynamics": True,
        "derived_xml_sha256": hashlib.sha256(payload).hexdigest(),
    }
