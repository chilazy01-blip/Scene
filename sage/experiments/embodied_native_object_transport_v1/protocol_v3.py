"""One user-approved sequence revision within the unchanged phase deadline/budget."""

import argparse
from pathlib import Path
import time
from .protocol_v2 import authorize as parent
from .protocol import reserve as parent_reserve, project_target
from .report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def authorize(root):
    p = parent(root)
    v = read_bound_json(root / "VERSION_03_PROTOCOL.json")
    assert v["version"] == 3 and v["additional_versions_authorized"] == 1
    for b in [v["parent"], v["phase_one_review"], v["geometry"], *v["dependencies"].values()]:
        assert sha256_file(Path(b["path"])) == b["sha256"]
    assert v["deadline_epoch_utc"] == p["deadline_epoch_utc"]
    return p


def reserve(root, output, ceiling):
    authorize(root)
    assert output == root / "version_03/full"
    return parent_reserve(root, output, ceiling)


def freeze(root):
    p = parent(root)
    out = root / "VERSION_03_PROTOCOL.json"
    assert not out.exists() and time.time() < p["deadline_epoch_utc"]
    route = read_bound_json(root / "SEQUENCE_ROUTE_PREFLIGHT_V3.json")
    selected = route["attempts"][3]
    checked = [s for s in selected["samples"] if 1.80 <= s["x"] <= 1.95]
    assert len(checked) == 248
    assert all(not s["forbidden"] and s["depth"] <= .01 for s in checked)
    safe_save(out, {
        "schema": "native-mug-post-stop-reach-revision/v3", "version": 3,
        "additional_versions_authorized": 1,
        "user_authorization_verbatim": "先做尝试。还有每次做尝试时建议失败的轨迹也尽量保持任务完整，以更好地确定是哪一步出了问题，除此之外没有别的问题了，继续执行吧",
        "authorized_change": "neutral held-arm approach, brake and settle, then bent-elbow two-segment raise and existing grasp; actual-state FK checks all62 raise points before execution; no relaxation of target projection or any physical safety gate",
        "failure_policy": "retain whole executed trajectory and rejected command; distinguish task failures from physical safety stops; do not manufacture unexecuted later stages or force unsafe continuation",
        "parent": _file_binding(root / "VERSION_02_PROTOCOL.json"),
        "phase_one_review": _file_binding(root / "PHASE_01_PARTIAL_REVIEW.json"),
        "dependencies": {n: _file_binding(Path(__file__).with_name(n)) for n in (
            "protocol_v3.py", "engine_v3.py", "task_v3.py", "audit_v3.py", "sequence_preflight_v3.py", "sequence_route_preflight_v3.py")},
        "geometry": _file_binding(root / "SEQUENCE_ROUTE_PREFLIGHT_V3.json"),
        "nominal_route_clearance": "candidate4 passes rootX1.80..1.95 at nominal posture; candidate4 failed at1.75 and all other candidate failures preserved; actual-state62point checks mandatory",
        "deadline_epoch_utc": p["deadline_epoch_utc"],
        "max_new_physics_steps": 40000, "cumulative_native_cap": 60000,
        "shared_step_ledger": str(root / "COST.json"),
        "admission": _file_binding(root / "version_01/admission/REPORT.json"),
        "frozen_epoch_utc": time.time(),
    })
    print({"version": 3, "frozen": True, "physics_steps": 0}, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    freeze(ap.parse_args().root)
