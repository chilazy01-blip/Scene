"""Validate the second and last causal version against the unchanged master plan."""

from pathlib import Path
from sage.experiments.embodied_native_walk_v1.motion_gate import (
    require_motion_protocol as master,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def require_motion_protocol(root):
    old = master(root)
    p = read_bound_json(root / "REVISION_02_PROTOCOL.json")
    if (
        p["parent"]["sha256"] != sha256_file(root / "MOTION_PROTOCOL.json")
        or p["version"] != 2
        or old["max_causal_versions"] < 2
    ):
        raise ValueError("invalid causal version")
    for key in (
        "conditions",
        "case_bindings",
        "inputs",
        "reference_base",
        "acceptance_limits",
        "official_motor_arrays",
        "max_total_physics_steps",
        "max_causal_versions",
        "brake_ticks",
    ):
        if p[key] != old[key]:
            raise ValueError("unapproved non-startup change: " + key)
    for b in p["dependencies"].values():
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("revision dependency changed")
    return p
