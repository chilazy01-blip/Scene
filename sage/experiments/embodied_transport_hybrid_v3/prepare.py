"""Freeze coherent reference feedback, reusing unchanged certified geometry."""

import argparse
from pathlib import Path
import time
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def prepare(root, parent):
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    (root / "model").symlink_to(parent / "model", target_is_directory=True)
    case = read_bound_json(parent / "CASE.json")
    case["protocol_root"] = str(root)
    save(root / "CASE.json", case)
    cert = read_bound_json(parent / "PREFLIGHT_SAFE.json")
    if not cert["passed"]:
        raise ValueError("uncertified geometry")
    cert.update(
        case=_file_binding(root / "CASE.json"),
        parent_certificate=_file_binding(parent / "PREFLIGHT_SAFE.json"),
        implementation=_file_binding(Path(__file__)),
        geometry_unchanged=True,
    )
    save(root / "PREFLIGHT_SAFE.json", cert)
    deps = {}
    for package in (
        "embodied_transport_v1",
        "embodied_transport_hybrid_v1",
        "embodied_transport_hybrid_v2",
        "embodied_transport_hybrid_v3",
    ):
        for p in sorted((Path(__file__).parent.parent / package).glob("*.py")):
            if not p.name.startswith("test"):
                deps[package + "/" + p.name] = _file_binding(p)
    protocol = {
        "schema": "authorized-hybrid-transport/v3",
        "case": _file_binding(root / "CASE.json"),
        "preflight": _file_binding(root / "PREFLIGHT_SAFE.json"),
        "created_utc_timestamp": time.time(),
        "causal_revision": 3,
        "max_causal_versions": 3,
        "repeat_rejected_identical_case": False,
        "revision_evidence": _file_binding(parent / "REJECTED_COMMAND_REPLAY.json"),
        "control": "SONIC22 raw targets unchanged; independent right-arm7 world-space IK with official kp/kd/effort and declared right-arm qfrc_bias; receding future reference is recomputed from actual posture before encoder",
        "guard_scope": "full29 finite policy outputs, range/slew only consumed SONIC22; all29 actual mixed targets separately range/slew guarded; unused SONIC arm target is not sent to any actuator",
        "history": "actual mixed29 targets inversely mapped into raw last_action history",
        "active_budgets_ticks": [100, 300, 500, 1000, 1500, 2000],
        "per_process_wall_s": 180,
        "physical_thresholds": "unchanged .65m pelvis/.5up/.01m penetration/600N/.5433987842330933 slew; no active support/applied forces; only explicitly declared arm motor bias",
        "task_contract": "standing true pickup/place is qualification only, not full transport; source clear whole object20mm and opposing for100substeps; release on target and hand-free stable100substeps; full transport requires real approach and carry foot cycles",
        "dependencies": deps,
        "parent_dependencies": {},
        "hybrid_parent_dependencies": {},
        "user_authorization": "user explicitly approved independent upper limb control after plain-language explanation",
    }
    save(root / "PROTOCOL.json", protocol)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--parent", type=Path, required=True)
    a = p.parse_args()
    prepare(a.root, a.parent)
