"""Final bounded carried-load integration revision, same physical task identity."""

import argparse
from pathlib import Path
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def prepare(root, parent):
    evidence = read_bound_json(parent / "TUCK_JOINT_ROLES.json")
    if not evidence["passed"] or root.exists():
        raise ValueError("no safe geometric path, or existing root")
    root.mkdir(parents=True)
    (root / "model").symlink_to(parent / "model", target_is_directory=True)
    c = read_bound_json(parent / "CASE.json")
    c.update(
        protocol_root=str(root),
        compact_wrist_relative_to_base_m=evidence["selected_wrist_relative_to_base_m"],
    )
    save(root / "CASE.json", c)
    cert = read_bound_json(parent / "PREFLIGHT_SAFE.json")
    cert.update(
        case=_file_binding(root / "CASE.json"),
        parent_certificate=_file_binding(parent / "PREFLIGHT_SAFE.json"),
    )
    save(root / "PREFLIGHT_SAFE.json", cert)
    p = read_bound_json(parent / "PROTOCOL.json")
    p.update(
        case=_file_binding(root / "CASE.json"),
        compact_evidence=_file_binding(parent / "TUCK_JOINT_ROLES.json"),
        previous_rejection=_file_binding(parent / "REJECTED_COMMAND_REPLAY.json"),
        causal_revision=2,
        max_causal_versions=2,
        finite_stage="second and final carried-load integration revision; physical compact phase before carry, same original safety/clearance/grip/footstep/release gates; no blind identical retries",
    )
    for package in ("embodied_transport_contact_v3", "embodied_transport_contact_v4"):
        for f in sorted((Path(__file__).parent.parent / package).glob("*.py")):
            if not f.name.startswith("test"):
                p["dependencies"][package + "/" + f.name] = _file_binding(f)
    save(root / "PROTOCOL.json", p)
    print(
        {
            "prepared_full_revision": 2,
            "compact_relative_m": c["compact_wrist_relative_to_base_m"],
        }
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--parent", type=Path, required=True)
    a = p.parse_args()
    prepare(a.root, a.parent)
