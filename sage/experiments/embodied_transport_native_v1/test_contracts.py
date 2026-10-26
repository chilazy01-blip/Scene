"""Regression: full scene collision must never alias flex to the last geom."""

from types import SimpleNamespace
import numpy as np
import mujoco
import pytest
from .contacts import participant, foot_metrics


def test_flex_participant_is_not_negative_geom_lookup():
    m = mujoco.MjModel.from_xml_string(
        '<mujoco><worldbody><body name="probe"><freejoint/><geom name="last_geom" type="sphere" size=".01" mass=".1"/></body></worldbody><deformable><flex name="native_floor" dim="2" body="world" radius=".001" vertex="-1 -1 0 1 -1 0 0 1 0" element="0 1 2"/></deformable></mujoco>'
    )
    c = SimpleNamespace(geom=[0, -1], flex=[-1, 0])
    p = participant(m, c, 1)
    assert p["name"] == "native_floor" and p["geom"] == -1 and p["flex"] == 0
    assert participant(m, c, 0)["name"] == "last_geom"


def test_sole_metrics_exclude_visual_mesh_geometry():
    mesh = '<asset><mesh name="tetra" vertex="0 0 0 .01 0 0 0 .01 0 0 0 .01" face="0 1 2 0 1 3 0 2 3 1 2 3"/></asset>'
    bodies = "".join(
        f'<body name="{s}_ankle_roll_link" pos="0 0 .1"><geom type="box" size=".1 .05 .02"/><geom type="mesh" mesh="tetra" contype="0" conaffinity="0"/></body>'
        for s in ("left", "right")
    )
    m = mujoco.MjModel.from_xml_string(
        "<mujoco>" + mesh + "<worldbody>" + bodies + "</worldbody></mujoco>"
    )
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    result = foot_metrics(mujoco, m, d)
    assert np.isclose(result["left"]["sole_clearance_m"], 0.08)
    assert result["right"]["ground_contact_force_max_n"] == 0


@pytest.mark.xfail(
    strict=True,
    reason="Installed MuJoCo 3.7.0 returns zero box/rigid-triangle contacts in this minimal positive-overlap case; blocks native walking admission, must not count as passed",
)
def test_real_rigid_triangle_contacts_count_as_foot_support():
    bodies = "".join(
        f'<body name="{s}_ankle_roll_link" pos="{x} 0 .019"><freejoint/><geom type="box" size=".1 .05 .02" mass="1"/></body>'
        for s, x in [("left", -0.2), ("right", 0.2)]
    )
    floor = '<deformable><flex name="native_floor" dim="2" body="world" radius=".001" vertex="-2 -2 0 2 -2 0 0 2 0" element="0 1 2"><contact selfcollide="none" internal="false" contype="2" conaffinity="1"/></flex></deformable>'
    m = mujoco.MjModel.from_xml_string(
        "<mujoco><worldbody>" + bodies + "</worldbody>" + floor + "</mujoco>"
    )
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    assert d.ncon > 0 and m.flex_rigid[0]
    assert any(
        participant(m, c, s)["name"] == "native_floor"
        for c in d.contact
        for s in (0, 1)
    )
    result = foot_metrics(mujoco, m, d)
    assert all(result[s]["ground_contact_force_max_n"] > 0 for s in ("left", "right"))
