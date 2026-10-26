"""Freeze the corrected FK-certified corridor, preserving rejected preflight."""

import argparse
from pathlib import Path
import time
from .prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def freeze(root):
    path = root / "PROTOCOL.json"
    if path.exists():
        raise FileExistsError(path)
    if not read_bound_json(root / "PREFLIGHT_SAFE.json")["passed"]:
        raise ValueError("preflight rejected")
    p = {
        "schema": "authorized-hybrid-transport/v1",
        "created_utc_timestamp": time.time(),
        "user_authorization": "2026-10-20 user: 可以，先按照这个想法去调整; permit independent upper-limb precise control while retaining SONIC locomotion",
        "case": _file_binding(root / "CASE.json"),
        "preflight": _file_binding(root / "PREFLIGHT_SAFE.json"),
        "active_budgets_ticks": [100, 300, 500, 1000, 1500, 2000],
        "per_process_wall_s": 180,
        "max_causal_versions": 3,
        "repeat_rejected_identical_case": False,
        "controller": "unchanged raw SONIC targets for22 joints; seven right-arm Cartesian reference IK targets using unchanged official kp/kd/effort plus explicitly declared right-arm qfrc_bias gravity compensation; finger PD unchanged",
        "applied_action_history": "all29 actually applied mixed targets mapped back to raw action space, not unused SONIC arm outputs",
        "physical_thresholds": "unchanged .65m pelvis/.5up/.01m penetration/600N/.5433987842330933 slew; no active support or applied force; gravity compensation only as declared arm motor torque",
        "source_guard": "before stable acquisition, >20mm displacement during reach or >4 physical substeps unsupported/nonopposing rejects",
        "scope": "standing pickup/place is only a new-controller qualification, not full autonomous transport; generated room retained, privileged simulator state feedback",
        "task_contract": "genuine free-body pickup with opposing contact and whole object bottom>=20mm above source for100substeps; target support before release; retract and stable hand-free placement100substeps; full mode additionally real approach/carry walking/stop",
        "causal_revision": 2,
        "controller_extra": "per-control-tick world-pose IK feedback for right arm; no servo during carry, so payload follows body",
        "revision_evidence": _file_binding(
            root.parent
            / "embodied_transport_hybrid_20261020_v1/attempt_01/active_0500/REPORT.json"
        ),
        "hybrid_parent_dependencies": {
            p.name: _file_binding(p)
            for p in sorted(
                (Path(__file__).parent.parent / "embodied_transport_hybrid_v1").glob(
                    "*.py"
                )
            )
            if not p.name.startswith("test")
        },
        "dependencies": {
            p.name: _file_binding(p)
            for p in sorted(Path(__file__).parent.glob("*.py"))
            if not p.name.startswith("test")
        },
        "parent_dependencies": {
            p.name: _file_binding(p)
            for p in sorted(
                (Path(__file__).parent.parent / "embodied_transport_v1").glob("*.py")
            )
            if not p.name.startswith("test")
        },
    }
    save(path, p)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    freeze(p.parse_args().root)
