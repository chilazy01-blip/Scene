"""Inspect the frozen ONNX graph without adding ONNX dependencies or inference."""

import argparse
from collections import Counter
from pathlib import Path
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
    sha256_file,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def fields(blob):
    data = memoryview(blob)
    index = 0

    def varint():
        nonlocal index
        value = shift = 0
        while index < len(data) and shift < 70:
            byte = data[index]
            index += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
            shift += 7
        raise ValueError("invalid protobuf varint")

    while index < len(data):
        key = varint()
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ValueError("invalid field zero")
        if wire == 0:
            value = varint()
        elif wire in (1, 2, 5):
            length = varint() if wire == 2 else (8 if wire == 1 else 4)
            if length > len(data) - index:
                raise ValueError("truncated protobuf")
            value = data[index : index + length]
            index += length
        else:
            raise ValueError("unsupported protobuf wire")
        yield number, wire, value


def graph_nodes(path):
    # ONNX ModelProto.graph=7, GraphProto.node=1, NodeProto op_type=4/name=3.
    graphs = [
        value
        for number, wire, value in fields(path.read_bytes())
        if number == 7 and wire == 2
    ]
    if len(graphs) != 1:
        raise ValueError("expected one top-level ONNX graph")
    nodes = []
    for number, wire, value in fields(graphs[0]):
        if number != 1 or wire != 2:
            continue
        node = {}
        for field, kind, item in fields(value):
            if kind == 2 and field in (3, 4, 7):
                node[{3: "name", 4: "op_type", 7: "domain"}[field]] = bytes(
                    item
                ).decode("utf8")
        if "op_type" not in node:
            raise ValueError("node missing op_type")
        nodes.append(node)
    return nodes


def run(root):
    output = root / "QUANTIZATION_REVIEW.json"
    if output.exists():
        raise FileExistsError(output)
    sensitivity = read_bound_json(root / "POLICY_SENSITIVITY.json")
    report = read_bound_json(Path(sensitivity["report"]["path"]))
    binding = report["inputs"]["encoder"]
    path = Path(binding["path"])
    if sha256_file(path) != binding["sha256"]:
        raise ValueError("encoder changed")
    nodes = graph_nodes(path)
    counts = Counter(n["op_type"] for n in nodes)
    quantizers = [
        n
        for n in nodes
        if n["op_type"]
        in ("Round", "Floor", "Ceil", "QuantizeLinear", "DequantizeLinear")
    ]
    source = Path(
        "/data/wsj/main/scene_runs/codex_trellis_v2/embodied_data_stability_sonic_readmission_20261018_v1/source/gear_sonic"
    )
    code = source / "trl/modules/universal_token_modules.py"
    export = source / "utils/inference_helpers.py"
    result = {
        "schema": "frozen-sonic-quantization-route-review/v1",
        "encoder": binding,
        "graph_node_count": len(nodes),
        "op_counts": dict(counts),
        "quantization_nodes": quantizers,
        "source_bindings": [_file_binding(code), _file_binding(export)],
        "sensitivity": _file_binding(root / "POLICY_SENSITIVITY.json"),
        "findings": [
            {
                "frame": p["frame"],
                "finite_difference_rank_at_relative_1e_3": sum(
                    v > max(p["arm_singular_values"]) * 0.001
                    for v in p["arm_singular_values"]
                ),
                "baseline_arm_command_rms_rad": p["baseline_arm_command_error_rms_rad"],
                "bounded_reference_correction_rms_rad": p[
                    "probe_arm_command_error_rms_rad"
                ],
                "non_arm_command_change_rad": p["non_arm_command_max_change_rad"],
            }
            for p in sensitivity["probes"]
        ],
        "interpretation": "If Round nodes occur in the token encoder, discrete token changes explain observed dead zones and identical finite-difference columns. Small-angle smooth-reference inversion cannot be treated as a differentiable7DOF task-space servo. This does not prove global impossibility, and neither candidate has been executed physically.",
        "proposed_routes": [
            "retain raw SONIC29: design separately bounded quantization-aware reference search and whole-body prediction qualification, not another geometric grasp-path tweak",
            "if user explicitly approves control-contract change: separate upper-limb task-space control, first standing pickup/place qualification then whole-body carrying admission",
        ],
        "new_physics_steps": 0,
        "new_policy_inferences": 0,
        "controller_changed": False,
        "task_passed": False,
        "implementation": _file_binding(Path(__file__)),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output, result)
    print(
        {
            "graph_nodes": len(nodes),
            "quantization_nodes": quantizers,
            "findings": result["findings"],
            "new_physics_steps": 0,
        }
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
