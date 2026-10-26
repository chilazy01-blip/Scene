import hashlib
import json
from pathlib import Path

from sage.experiments.embodied_data_stability_v1.audit_sonic_readmission import (
    EXPECTED_ARTIFACTS,
    EXPECTED_INTERFACES,
    build_gates,
    inspect_artifacts,
    inspect_control_boundary,
    inspect_source_tree,
    validate_inference_report,
)


def _artifact_rows(ready: bool = True):
    return {name: {"ready": ready} for name in EXPECTED_ARTIFACTS}


def _inference_report(*, bad_decoder_shape: bool = False):
    models = {}
    for name, expected in EXPECTED_INTERFACES.items():
        output_shape = list(expected["output_shape"])
        if name == "model_decoder" and bad_decoder_shape:
            output_shape[-1] += 1
        models[name] = {
            "inputs": [
                {
                    "name": expected["input_name"],
                    "shape": list(expected["input_shape"]),
                    "type": "tensor(float)",
                }
            ],
            "outputs": [
                {
                    "name": expected["output_name"],
                    "shape": output_shape,
                    "type": "tensor(float)",
                }
            ],
            "output_shape_observed": output_shape,
            "output_all_finite": True,
            "zero_output_sha256": expected["zero_output_sha256"],
        }
    return {"models": models, "model_forwards": 44}


def test_artifact_inspection_requires_exact_size_and_hash(tmp_path: Path, monkeypatch):
    expected = {}
    for name, row in EXPECTED_ARTIFACTS.items():
        path = tmp_path / row["relative_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = name.encode("utf-8")
        path.write_bytes(payload)
        expected[name] = {
            **row,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    monkeypatch.setattr(
        "sage.experiments.embodied_data_stability_v1.audit_sonic_readmission.EXPECTED_ARTIFACTS",
        expected,
    )
    report = inspect_artifacts(tmp_path)
    assert all(row["ready"] for row in report.values())
    (tmp_path / expected["model_decoder"]["relative_path"]).write_bytes(b"changed")
    report = inspect_artifacts(tmp_path)
    assert report["model_decoder"]["ready"] is False


def test_source_tree_counts_lfs_and_detects_exact_blob_identity(tmp_path: Path):
    (tmp_path / "nested").mkdir()
    normal = b"normal\n"
    pointer = (
        b"version https://git-lfs.github.com/spec/v1\n"
        b"oid sha256:" + b"1" * 64 + b"\nsize 12345\n"
    )
    (tmp_path / "normal.txt").write_bytes(normal)
    (tmp_path / "nested" / "asset.bin").write_bytes(pointer)

    def blob_oid(data: bytes) -> str:
        return hashlib.sha1(
            f"blob {len(data)}\0".encode("ascii") + data,
            usedforsecurity=False,
        ).hexdigest()

    git_entries = {
        "normal.txt": {"mode": "100644", "type": "blob", "oid": blob_oid(normal)},
        "nested/asset.bin": {
            "mode": "100644",
            "type": "blob",
            "oid": blob_oid(pointer),
        },
    }
    report = inspect_source_tree(tmp_path, git_entries=git_entries)
    assert report["file_count"] == 2
    assert report["regular_file_count"] == 2
    assert report["symlink_count"] == 0
    assert report["lfs_pointer_count"] == 1
    assert report["lfs_pointer_claimed_content_bytes"] == 12345
    assert report["commit_tree_exact_match"] is True

    (tmp_path / "normal.txt").write_text("modified\n", encoding="utf-8")
    report = inspect_source_tree(tmp_path, git_entries=git_entries)
    assert report["commit_tree_exact_match"] is False
    assert report["blob_mismatch_count"] == 1


def test_inference_contract_is_fail_closed_on_shape_change():
    valid = validate_inference_report(_inference_report())
    assert valid["executed"] is True
    assert valid["contract_matches"] is True
    invalid = validate_inference_report(_inference_report(bad_decoder_shape=True))
    assert invalid["contract_matches"] is False
    assert invalid["contract_checks"]["model_decoder"]["passed"] is False


def test_control_boundary_reports_external_hands(tmp_path: Path):
    deploy = tmp_path / "gear_sonic_deploy"
    model_dir = deploy / "g1"
    source_dir = deploy / "src/g1/g1_deploy_onnx_ref/src"
    include_dir = deploy / "src/g1/g1_deploy_onnx_ref/include"
    model_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    include_dir.mkdir(parents=True)
    body_joints = "".join(f'<joint name="body_{i}"/>' for i in range(29))
    body_acts = "".join(f'<motor name="body_{i}"/>' for i in range(29))
    hand_joints = "".join(f'<joint name="right_hand_{i}"/>' for i in range(14))
    hand_acts = "".join(f'<motor name="right_hand_{i}"/>' for i in range(14))
    (model_dir / "g1_29dof.xml").write_text(
        f"<mujoco><worldbody>{body_joints}</worldbody><actuator>{body_acts}</actuator></mujoco>"
    )
    (model_dir / "g1_29dof_with_hand.xml").write_text(
        f"<mujoco><worldbody>{body_joints}{hand_joints}</worldbody>"
        f"<actuator>{body_acts}{hand_acts}</actuator></mujoco>"
    )
    (source_dir / "g1_deploy_onnx_ref.cpp").write_text(
        "GetHandPose(true); GetHandPose(false); setAllJointsCommand();"
    )
    (include_dir / "dex3_hands.hpp").write_text("MAX_DELTA_Q = 0.25; max_close_ratio_;")
    report = inspect_control_boundary(tmp_path)
    assert report["policy_action_dimension"] == 29
    assert report["with_hand_mujoco_model"]["actuator_count"] == 43
    assert report["dex3_targets_are_external_inputs"] is True
    assert report["contact_aware_grasp_closed_loop_present"] is False


def test_gates_keep_native_and_grasp_closed_when_dependencies_are_missing():
    inference = validate_inference_report(_inference_report())
    host = {
        "gpu": {"accessible": True},
        "cuda_toolkit": {"nvcc_available": True},
        "cmake": {"available": False},
        "tensorrt": {"complete_for_source_find_module": False},
        "onnxruntime_cpp": {"complete": False},
    }
    control = {
        "with_hand_mujoco_model": {"hand_actuator_count": 14},
        "contact_aware_grasp_closed_loop_present": False,
    }
    gates, blockers = build_gates(
        artifacts=_artifact_rows(),
        source_tree={
            "commit_tree_exact_match": True,
            "lfs_pointer_count": 1275,
            "native_deploy_lfs_pointer_count": 151,
        },
        inference=inference,
        host=host,
        control=control,
        planner_present=False,
    )
    assert gates["policy_weights_ready"] is True
    assert gates["cpu_structural_inference_ready"] is True
    assert gates["official_native_runtime_ready"] is False
    assert gates["grasp_ab_ready"] is False
    assert gates["production_accepted"] is False
    conditions = {row["condition"] for row in blockers}
    assert "cmake_available" in conditions
    assert "planner_present_and_reviewed" in conditions
    assert "common_external_hand_controller_frozen" in conditions
