"""Archive zero-motion readiness work while the environment confirmation is pending."""

import argparse
from pathlib import Path
import ast
import xml.etree.ElementTree as ET
from .acceptance_v1 import LIMITS
from .preflight import authorize
from .motion_gate import require_motion_protocol
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_braking_acceptance import (
    LIMITS as OLD_LIMITS,
)


def run(root):
    authorize(root)
    test = root / "DRAFT_ACCEPTANCE_TESTS.xml"
    suites = ET.parse(test).getroot().findall("testsuite")
    tests = sum(int(s.get("tests", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    if tests != 19 or failures:
        raise ValueError("readiness regression evidence missing or failed")
    comparisons = {
        "penetration_unchanged": LIMITS["maximum_penetration_m"]
        == native.MAX_PENETRATION_M,
        "contact_force_unchanged": LIMITS["maximum_contact_force_n"]
        == native.MAX_CONTACT_FORCE_N,
        "physics_timestep_unchanged": LIMITS["simulation_dt_s"]
        == native.SIMULATION_DT_S,
        "pelvis_not_relaxed": LIMITS["minimum_pelvis_m"]
        >= max(native.MIN_PELVIS_HEIGHT_M, OLD_LIMITS["minimum_pelvis_m"]),
        "upright_not_relaxed": LIMITS["minimum_up_component"]
        >= max(native.MIN_PELVIS_UP_COMPONENT, OLD_LIMITS["minimum_up_component"]),
        "standing_drift_not_relaxed": LIMITS["maximum_stand_horizontal_drift_m"]
        <= OLD_LIMITS["maximum_hold_horizontal_drift_m"],
        "standing_speed_not_relaxed": LIMITS["maximum_stand_root_speed_m_s"]
        <= OLD_LIMITS["maximum_hold_horizontal_speed_m_s"],
        "joint_velocity_not_relaxed": LIMITS["maximum_stand_joint_velocity_rms_rad_s"]
        <= OLD_LIMITS["maximum_hold_joint_velocity_rms_rad_s"],
        "double_support_not_relaxed": LIMITS["minimum_stand_both_feet_contact_fraction"]
        >= OLD_LIMITS["minimum_hold_both_feet_contact_fraction"],
    }
    assert all(comparisons.values())
    gate_error = None
    try:
        require_motion_protocol(root)
    except PermissionError as e:
        gate_error = str(e)
    assert (
        gate_error
        and not (root / "ENVIRONMENT_APPROVAL.json").exists()
        and not (root / "MOTION_PROTOCOL.json").exists()
    )
    scene = read_bound_json(root / "model/SCENE.json")
    model = load_model(scene["model"]["path"])
    assert (model.nq, model.nv, model.nu, model.nbody) == (50, 49, 43, 50)
    source_files = [
        Path(__file__).with_name(n)
        for n in (
            "acceptance_v1.py",
            "motion_gate.py",
            "test_acceptance_v1.py",
            "readiness_v1.py",
        )
    ]
    calls = []
    for f in source_files:
        for node in ast.walk(ast.parse(f.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "mj_step"
            ):
                calls.append(str(f))
    assert not calls
    result = {
        "schema": "native-walk-pre-motion-readiness/v1",
        "program_tests_passed": True,
        "unit_tests": tests,
        "synthetic_metric_tests_are_not_robot_success": True,
        "test_report": _file_binding(test),
        "source_bindings": {f.name: _file_binding(f) for f in source_files},
        "limits": dict(LIMITS),
        "original_limit_comparisons": comparisons,
        "model_dimensions": {"nq": 50, "nv": 49, "nu": 43, "nbody": 50},
        "motion_gate_denial": gate_error,
        "user_environment_confirmation_pending": True,
        "motion_authorized": False,
        "physics_steps": 0,
        "task_passed": False,
        "robot_episodes": 0,
        "standard_data_samples": 0,
        "scene": _file_binding(root / "model/SCENE.json"),
        "static_review": _file_binding(root / "STATIC_REVIEW.json"),
        "visual_review": _file_binding(root / "VISUAL_REVIEW.json"),
        "scope": "acceptance logic and fail-closed gating ready; actual controller runner, independent audits and dynamic task remain unqualified and require exact environment approval first",
        "implementation": _file_binding(Path(__file__)),
    }
    save(root / "DRAFT_READINESS.json", result)
    print(
        {
            "unit_tests": tests,
            "guard_limit_comparisons_passed": all(comparisons.values()),
            "motion_authorized": False,
            "physics_steps": 0,
            "task_passed": False,
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
