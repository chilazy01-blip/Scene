"""Reconstruct encoder references and measured stop events, without physics."""

import argparse
from pathlib import Path
from .control import reference
from sage.experiments.embodied_locomotion_v1.reference_audit import audit_run
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _make_session,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    result_path = root / "REFERENCE_AUDIT.json"
    if result_path.exists():
        raise FileExistsError(result_path)
    planner = _make_session(
        native.DEFAULT_BUNDLE / "planner/target_vel/V2/planner_sonic.onnx"
    )
    cache = {}
    directories = [root / "attempt_01/standing_admission"] + [
        root / "continuation_01" / name
        for name in (
            "standing_short",
            "standing_full",
            "walking_admission",
            "walking_short",
            "walking_full",
        )
    ]
    results = []
    for directory in directories:
        report = read_bound_json(directory / "REPORT.json")
        mode = report["carry_mode"]
        if mode not in cache:
            q, v, _ = reference(planner, report["case_config"])
            cache[mode] = (q, v)
        output = directory / "REFERENCE_AUDIT.json"
        if output.exists():
            raise FileExistsError(output)
        result = audit_run(directory, *cache[mode])
        result["carry_reference_builder"] = _file_binding(
            Path(__file__).with_name("control.py")
        )
        result.pop("content_sha256_excluding_this_field", None)
        result["content_sha256_excluding_this_field"] = canonical_sha256(result)
        write_json_atomic(output, result)
        results.append(_file_binding(output))
        print(
            directory.name, result["passed"], result["reconstructed_inputs"], flush=True
        )
    summary = {
        "schema": "ordered-carry-reference-integrity/v2",
        "passed": all(read_bound_json(Path(b["path"]))["passed"] for b in results),
        "audits": results,
        "physics_steps": 0,
        "implementation": _file_binding(Path(__file__)),
    }
    summary["content_sha256_excluding_this_field"] = canonical_sha256(summary)
    write_json_atomic(result_path, summary)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
