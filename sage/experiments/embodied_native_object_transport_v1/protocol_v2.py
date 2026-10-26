"""Second and final causal task version; no model or physical-gate changes."""

import argparse
from pathlib import Path
from .protocol import authorize as parent, reserve as parent_reserve, project_target
from .report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def authorize(root):
    p = parent(root)
    v = read_bound_json(root / "VERSION_02_PROTOCOL.json")
    assert v["parent"]["sha256"] == sha256_file(root / "PROTOCOL.json")
    assert v["version"] == 2 <= p["max_causal_versions"]
    for b in v["dependencies"].values():
        assert sha256_file(Path(b["path"])) == b["sha256"]
    return p


def reserve(root, output, ceiling):
    authorize(root)
    return parent_reserve(root, output, ceiling)


def freeze(root):
    p = parent(root)
    assert not (root / "VERSION_02_PROTOCOL.json").exists()
    cause = read_bound_json(root / "PLANNING_TOLERANCE_CAUSAL_PROBE.json")
    assert cause["outcomes"][1]["failure"] is None
    original = Path(__file__).with_name("task.py").read_text()
    changed = Path(__file__).with_name("task_v2.py").read_text()
    import ast

    assert ast.dump(ast.parse(changed)) == ast.dump(
        ast.parse(original.replace("> 0.005", "> 0.010"))
    )
    dependencies = {
        n: _file_binding(Path(__file__).with_name(n))
        for n in (
            "task_v2.py",
            "engine_v2.py",
            "audit_v2.py",
            "protocol_v2.py",
            "report_safe_engine.py",
            "failure_probe.py",
        )
    }
    dependencies["cause"] = _file_binding(root / "PLANNING_TOLERANCE_CAUSAL_PROBE.json")
    dependencies["prior_failure"] = _file_binding(root / "version_01/full/REPORT.json")
    dependencies["prior_audit"] = _file_binding(root / "version_01/full/AUDIT.json")
    safe_save(
        root / "VERSION_02_PROTOCOL.json",
        {
            "schema": "native-mug-final-planning-revision/v2",
            "version": 2,
            "parent": _file_binding(root / "PROTOCOL.json"),
            "dependencies": dependencies,
            "only_causal_change": "Task IK position-residual soft gate5mm->10mm, actual reach15mm already declared; no model, motor, collision, physical speed/acceleration gates or actual pickup/carry/release criteria changed",
            "shared_step_ledger": str(root / "COST.json"),
            "max_new_physics_steps": 40000,
            "unchanged_case": p["case"],
            "reused_exact_admission": _file_binding(
                root / "version_01/admission/REPORT.json"
            ),
            "admission_prefix_proof": "first100ticks have no arm IK and are unchanged; full new episode must reproduce fullqpos/qvel/warmstart from original admission exactly",
            "implementation": _file_binding(Path(__file__)),
        },
    )
    print({"version": 2, "frozen": True, "no_new_physics_yet": True}, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    freeze(ap.parse_args().root)
