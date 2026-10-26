"""Freeze the first of two bounded full-integration stopping revisions."""

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
    evidence = read_bound_json(parent / "STOPPING_REFERENCE_PROBE.json")
    if evidence["selected_carry_brake_duration_ticks"] != 75 or root.exists():
        raise ValueError("no justified stopping revision, or root exists")
    root.mkdir(parents=True)
    (root / "model").symlink_to(parent / "model", target_is_directory=True)
    case = read_bound_json(parent / "CASE.json")
    case.update(protocol_root=str(root), carry_brake_duration_ticks=75)
    save(root / "CASE.json", case)
    cert = read_bound_json(parent / "PREFLIGHT_SAFE.json")
    cert.update(
        case=_file_binding(root / "CASE.json"),
        parent_certificate=_file_binding(parent / "PREFLIGHT_SAFE.json"),
        geometry_unchanged=True,
    )
    save(root / "PREFLIGHT_SAFE.json", cert)
    p = read_bound_json(parent / "PROTOCOL.json")
    p.update(
        case=_file_binding(root / "CASE.json"),
        stopping_evidence=_file_binding(parent / "STOPPING_REFERENCE_PROBE.json"),
        causal_revision=1,
        max_causal_versions=2,
        finite_stage="two bounded carried-load stopping integration revisions; source brake/pick/release unchanged, original ranges/slew/physical/task gates unchanged",
    )
    for package in (
        "embodied_transport_contact_v1",
        "embodied_transport_contact_v2",
        "embodied_transport_contact_v3",
    ):
        for f in sorted((Path(__file__).parent.parent / package).glob("*.py")):
            if not f.name.startswith("test"):
                p["dependencies"][package + "/" + f.name] = _file_binding(f)
    save(root / "PROTOCOL.json", p)
    print({"prepared_full_revision": 1, "carry_brake_ticks": 75, "root": str(root)})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--parent", type=Path, required=True)
    a = p.parse_args()
    prepare(a.root, a.parent)
