from pathlib import Path

from sage.experiments.embodied_data_stability_v1.run_groot_decoupled_native import (
    PHASES,
    onnx_shape_matches,
    parse_lfs_pointer,
    phase_at,
)


def test_lfs_pointer_parser(tmp_path: Path):
    pointer = tmp_path / "policy.onnx"
    pointer.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:" + "a" * 64 + "\n"
        "size 1234\n",
        encoding="utf-8",
    )
    assert parse_lfs_pointer(pointer) == {"oid_sha256": "a" * 64, "size_bytes": 1234}


def test_phase_schedule_has_exact_boundary_behavior():
    assert phase_at(0.0)["name"] == "stand_settle"
    assert phase_at(1.999)["name"] == "stand_settle"
    assert phase_at(2.0)["name"] == "forward_walk"
    assert phase_at(5.999)["name"] == "forward_walk"
    assert phase_at(6.0)["name"] == "stand_stop"
    assert phase_at(sum(float(row["duration_seconds"]) for row in PHASES))["name"] == "stand_stop"


def test_onnx_interface_accepts_symbolic_batch_only():
    assert onnx_shape_matches(["batch_size", 516], 516)
    assert onnx_shape_matches([1, 15], 15)
    assert not onnx_shape_matches(["batch_size", "features"], 516)
    assert not onnx_shape_matches([2, 516], 516)
