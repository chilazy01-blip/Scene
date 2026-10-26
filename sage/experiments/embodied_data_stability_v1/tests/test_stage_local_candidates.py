from sage.experiments.embodied_data_stability_v1.stage_local_candidates import (
    lfs_pointer,
    unitree_joint_names,
    yaml_list_names,
)


def test_lfs_pointer_is_not_treated_as_a_model(tmp_path):
    path = tmp_path / "policy.onnx"
    path.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
        "size 123456\n",
        encoding="utf-8",
    )
    assert lfs_pointer(path) == {
        "pointer_only": True,
        "lfs_oid_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "declared_object_size_bytes": 123456,
    }


def test_yaml_list_names_preserves_top_level_section_order(tmp_path):
    path = tmp_path / "observations.yaml"
    path.write_text(
        "observations:\n"
        "  - name: first\n"
        "    enabled: true\n"
        "  - name: second\n"
        "encoder:\n"
        "  - name: third\n",
        encoding="utf-8",
    )
    assert yaml_list_names(path, "observations") == ["first", "second"]
    assert yaml_list_names(path, "encoder") == ["third"]


def test_unitree_joint_names_reads_static_python_without_importing_it(tmp_path):
    path = tmp_path / "unitree.py"
    path.write_text(
        "UNITREE_G1_29DOF_CFG = UnitreeArticulationCfg(\n"
        "    joint_sdk_names=['left_hip', 'right_hip'],\n"
        ")\n",
        encoding="utf-8",
    )
    assert unitree_joint_names(path) == ["left_hip", "right_hip"]
