import numpy as np
from .effort_adapter import native_torque


def test_model_range_is_respected_when_stricter_than_release_parameters():
    assert native_torque(np.array([-103.,104.]),[139.,139.],np.array([[-88.,88.],[-88.,88.]])).tolist()==[-88.,88.]


def test_release_effort_is_respected_when_stricter_than_model():
    assert native_torque(np.array([-103.,104.]),[25.,25.],np.array([[-88.,88.],[-88.,88.]])).tolist()==[-25.,25.]


def test_in_range_motor_commands_are_unchanged():
    assert native_torque(np.array([1.,-2.]),[139.,139.],np.array([[-88.,88.],[-88.,88.]])).tolist()==[1.,-2.]
