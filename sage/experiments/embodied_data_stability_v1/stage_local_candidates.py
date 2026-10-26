"""Freeze locally staged candidate facts without importing or running them.

This command is deliberately static: it hashes already acquired files, parses
JSON/XML/text, records host capability probes, and writes admission manifests.
It never downloads, installs, imports a candidate runtime, loads a model, or
runs physics.  Acquisition is a separate operation because it may need network
approval and may produce partial files that must not be mistaken for a checkout.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import re
import shutil
import tarfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .audit_candidates import write_json_atomic


GROOT_REPOSITORY = "NVlabs/GR00T-WholeBodyControl"
GROOT_COMMIT = "b042411fae38ee4d1af9aac82a37a1f8d14d6dd0"
UNITREE_REPOSITORY = "unitreerobotics/unitree_rl_lab"
UNITREE_COMMIT = "4960b84732b0c2ec593dccbfe963fda1bcd7b1e3"
MODEL_SUFFIXES = {".onnx", ".pt", ".pth", ".ckpt"}

DEFAULT_SOURCE_A_RUN = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_stretch_ai_admission_20260926_v1/full_body_milestone/"
    "feasibility_guard_v4/prepared/payload_data_20261009/"
    "native_parallel_12h_20261011"
)


class StagingError(RuntimeError):
    """Raised when an expected local acquisition artifact is absent or corrupt."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path, root: Path | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
    }
    if root is not None:
        try:
            record["relative_path"] = path.relative_to(root).as_posix()
        except ValueError:
            pass
    if path.is_file():
        record.update({"size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return record


def require_files(root: Path, relative_paths: Iterable[str]) -> list[Path]:
    paths = [root / name for name in relative_paths]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise StagingError(f"missing required staged file(s): {missing}")
    return paths


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StagingError(f"expected JSON object: {path}")
    return value


def lfs_pointer(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.stat().st_size > 4096:
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("version https://git-lfs.github.com/spec/v1"):
        return None
    oid = re.search(r"^oid sha256:([0-9a-f]{64})$", text, re.MULTILINE)
    size = re.search(r"^size ([0-9]+)$", text, re.MULTILINE)
    return {
        "pointer_only": True,
        "lfs_oid_sha256": oid.group(1) if oid else None,
        "declared_object_size_bytes": int(size.group(1)) if size else None,
    }


def archive_probe(path: Path) -> dict[str, Any]:
    result = file_record(path)
    result["gzip_valid"] = False
    result["tar_valid"] = False
    if not path.is_file():
        return result
    try:
        with gzip.open(path, "rb") as stream:
            while stream.read(1024 * 1024):
                pass
        result["gzip_valid"] = True
    except (OSError, EOFError):
        return result
    try:
        with tarfile.open(path, "r:gz") as archive:
            result["member_count"] = sum(1 for _ in archive)
        result["tar_valid"] = True
    except (OSError, tarfile.TarError):
        pass
    return result


def tar_probe(path: Path) -> dict[str, Any]:
    result = file_record(path)
    result["tar_valid"] = False
    if not path.is_file():
        return result
    try:
        with tarfile.open(path, "r:") as archive:
            result["member_count"] = sum(1 for _ in archive)
        result["tar_valid"] = True
    except (OSError, tarfile.TarError):
        pass
    return result


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def host_probe(modules: Iterable[str], executables: Iterable[str]) -> dict[str, Any]:
    return {
        "scope": "current Python interpreter and PATH only",
        "python": shutil.which("python"),
        "modules": {name: module_available(name) for name in modules},
        "executables": {name: shutil.which(name) for name in executables},
    }


def model_manifest(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in MODEL_SUFFIXES):
        row = file_record(path, root)
        pointer = lfs_pointer(path)
        row.update(pointer or {"pointer_only": False})
        rows.append(row)
    return rows


def xml_robot_summary(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    joints = [node.attrib for node in root.findall(".//joint") if node.get("name")]
    actuator_parent = root.find("actuator")
    actuators = [] if actuator_parent is None else [node.attrib for node in actuator_parent]
    return {
        "model": root.get("model"),
        "named_joint_count": len(joints),
        "joint_names": [row["name"] for row in joints],
        "actuator_count": len(actuators),
        "actuators": actuators,
    }


def yaml_list_names(path: Path, section: str) -> list[str]:
    """Extract ordered ``- name`` entries from one top-level YAML section."""
    names: list[str] = []
    active = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith((" ", "\t", "#")):
            active = line.rstrip() == f"{section}:"
            continue
        if active:
            match = re.match(r"\s+- name:\s*[\"']?([^\"'#]+)", line)
            if match:
                names.append(match.group(1).strip())
    return names


def unitree_joint_names(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    block = re.search(r"UNITREE_G1_29DOF_CFG\s*=.*?joint_sdk_names\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if not block:
        raise StagingError(f"could not locate G1 joint_sdk_names in {path}")
    return re.findall(r'[\"\']([^\"\']+)[\"\']', block.group(1))


def write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    write_json_atomic(path, dict(payload))


def stage_groot(run_root: Path, observed_at: str) -> dict[str, Any]:
    root = run_root / "staging" / "groot_wbc_sonic"
    source = root / "source"
    required = require_files(
        source,
        [
            "LICENSE",
            "README.md",
            "config.json",
            "gear_sonic_deploy/deploy.sh",
            "gear_sonic_deploy/g1/g1_29dof.xml",
            "gear_sonic_deploy/policy/sonic_v1_1/observation_config.yaml",
            "gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/include/control_policy.hpp",
            "gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/include/policy_parameters.hpp",
            "gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/include/robot_parameters.hpp",
            "gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/src/g1_deploy_onnx_ref.cpp",
            "docs/source/getting_started/download_models.md",
        ],
    )
    release = read_json(source / "config.json")
    robot = xml_robot_summary(source / "gear_sonic_deploy/g1/g1_29dof.xml")
    observation_path = source / "gear_sonic_deploy/policy/sonic_v1_1/observation_config.yaml"
    observation_names = yaml_list_names(observation_path, "observations")
    encoder_names = yaml_list_names(observation_path, "encoder")
    readme = (source / "README.md").read_text(encoding="utf-8")

    acquisitions = {
        "schema": "embodied-candidate-acquisition-attempts/v1",
        "observed_at": observed_at,
        "candidate_id": "groot_wbc_sonic",
        "network_used_during_prior_acquisition": True,
        "attempts": [
            {
                "method": "github_codeload_full_archive",
                "complete": False,
                "reason": "transfer timed out; retained as failure evidence and never extracted",
                "artifact": archive_probe(root / "source.tar.gz"),
            },
            {
                "method": "git_partial_clone_no_checkout",
                "complete": False,
                "reason": "checkout required many promised blobs; clone retained for pinned on-demand reads",
                "path": str(root / "source_partial_clone_failed_20261014"),
            },
            {
                "method": "pinned_git_archive_selected_files",
                "complete": True,
                "scope": "static S0 contract and entrypoint evidence only; not a full checkout",
                "artifacts": [
                    tar_probe(root / "selected_source.tar"),
                    tar_probe(root / "sonic_contract_source.tar"),
                ],
            },
        ],
    }
    write_manifest(root / "ACQUISITION_ATTEMPTS.json", acquisitions)

    pin = {
        "schema": "embodied-source-pin/v1",
        "observed_at": observed_at,
        "repository": GROOT_REPOSITORY,
        "commit": GROOT_COMMIT,
        "source_form": "pinned_selected_file_archives",
        "source_tree": str(source),
        "full_source_snapshot_ready": False,
        "static_admission_slice_ready": True,
        "selected_archives": [
            file_record(root / "selected_source.tar", root),
            file_record(root / "sonic_contract_source.tar", root),
        ],
        "required_static_files": [file_record(path, source) for path in required],
    }
    write_manifest(root / "PIN.json", pin)

    entrypoint = {
        "schema": "embodied-native-entrypoint/v1",
        "candidate_id": "groot_wbc_sonic",
        "selected_track": "sonic_v1_1_mujoco_sim",
        "entrypoint_defined": "Run the controller in simulation" in (
            source / "docs/source/getting_started/download_models.md"
        ).read_text(encoding="utf-8"),
        "command": [
            "./deploy.sh",
            "--cp", "policy/sonic_v1_1/model",
            "--obs-config", "policy/sonic_v1_1/observation_config.yaml",
            "--motor-kp-scale", "4,10=1.5",
            "--motor-kd-scale", "4,10=1.5",
            "sim",
        ],
        "working_directory": "gear_sonic_deploy",
        "evidence": "docs/source/getting_started/download_models.md",
        "locally_executable": False,
        "blockers": ["full source tree absent", "SONIC encoder/decoder/planner weights absent", "native build environment absent"],
    }
    write_manifest(root / "NATIVE_ENTRYPOINT.json", entrypoint)

    weights = model_manifest(source)
    weight_manifest = {
        "schema": "embodied-weight-manifest/v1",
        "candidate_id": "groot_wbc_sonic",
        "selected_variant": "sonic_v1_1",
        "release_manifest": release,
        "selected_required_files": release["variants"]["sonic_v1_1"]["deployment_files"],
        "selected_weight_ready": False,
        "reason": "Selected SONIC files are not staged; two unrelated decoupled-WBC ONNX paths are LFS pointers only.",
        "locally_seen_model_files": weights,
    }
    write_manifest(root / "WEIGHTS.json", weight_manifest)

    environment = {
        "schema": "embodied-native-environment-lock/v1",
        "candidate_id": "groot_wbc_sonic",
        "selected_track": "sonic_v1_1_mujoco_sim",
        "ready_for_native_reproduction": False,
        "declared_controller_frequency_hz": 50 if "run the controller at 50 Hz" in readme else None,
        "host_probe": host_probe(["mujoco", "numpy", "onnxruntime"], ["cmake", "nvidia-smi", "uv"]),
        "blockers": ["full dependency source/build lock not staged", "TensorRT deployment build not present", "selected model weights absent"],
    }
    write_manifest(root / "environment.lock.json", environment)

    license_manifest = {
        "schema": "embodied-component-license-evidence/v1",
        "candidate_id": "groot_wbc_sonic",
        "legal_conclusion": False,
        "components": [
            {"scope": "source", **file_record(source / "LICENSE", source)},
            {
                "scope": "model_weights",
                **file_record(
                    source / "decoupled_wbc/sim2mujoco/resources/robots/g1/policy/NVIDIA Open Model License",
                    source,
                ),
                "note": "Evidence copy only; selected SONIC weight bytes remain absent.",
            },
            {"scope": "third_party_and_robot_assets", "status": "unresolved", "manual_review_required": True},
        ],
        "distribution_status": "unresolved_internal_only",
    }
    write_manifest(root / "ASSET_LICENSES.json", license_manifest)

    contract = {
        "schema": "embodied-control-contract-evidence/v1",
        "candidate_id": "groot_wbc_sonic",
        "selected_variant": "sonic_v1_1",
        "identity": {"repository": GROOT_REPOSITORY, "commit": GROOT_COMMIT},
        "robot": {
            "model_dimensions": {"embodiment": "Unitree G1", "motor_count": 29, "mjcf": robot},
            "joint_and_actuator_order": {
                "mjcf_actuator_order": [row.get("joint") for row in robot["actuators"]],
                "hardware_order_source": "robot_parameters.hpp::G1JointIndex 0..28",
                "training_to_mujoco_mapping": "policy_parameters.hpp::isaaclab_to_mujoco",
            },
            "actuator_types_gains_limits": {
                "command": ["q_target", "dq_target", "kp", "kd", "tau_ff"],
                "gain_and_effort_source": "policy_parameters.hpp",
                "gain_scaling_flags": ["--motor-kp-scale", "--motor-kd-scale"],
            },
        },
        "policy": {
            "raw_interfaces": {
                "encoder_input_dimension": 1751,
                "decoder_input_dimension": 994,
                "token_dimension": 64,
                "action_tensor": {"name": "action", "dimension": 29, "dtype": "float32"},
            }
        },
        "observation": {
            "fields_order_units": {
                "base_history_order": observation_names,
                "encoder_order": encoder_names,
                "units_reference": "docs/source/references/observation_config.md",
            }
        },
        "action": {
            "duration_and_hold_semantics": {
                "controller_frequency_hz": 50,
                "target_formula": "target = action * action_scale + default_angle",
            }
        },
        "control": {
            "native_transition_semantics": ["INIT", "WAIT_FOR_CONTROL", "CONTROL", "operator stop/start/play"]
        },
        "frames": {
            "world_base_task_camera": {
                "v1_1_reference": "robot-heading-normalized target orientation",
                "teleop_targets": "local wrist/head position and orientation",
            }
        },
        "unknown_fields_block_adaptation": True,
        "evidence_files": [file_record(path, source) for path in required],
    }
    write_manifest(root / "CONTROL_CONTRACT.json", contract)
    return {"pin": pin, "entrypoint": entrypoint, "environment": environment, "contract": contract}


def stage_unitree(run_root: Path, observed_at: str) -> dict[str, Any]:
    root = run_root / "staging" / "unitree_rl_lab"
    source = root / "source"
    required = require_files(
        source,
        [
            "LICENCE",
            "README.md",
            "unitree_rl_lab.sh",
            "scripts/rsl_rl/play.py",
            "source/unitree_rl_lab/unitree_rl_lab/assets/robots/unitree.py",
            "source/unitree_rl_lab/unitree_rl_lab/tasks/locomotion/robots/g1/29dof/__init__.py",
            "source/unitree_rl_lab/unitree_rl_lab/tasks/locomotion/robots/g1/29dof/velocity_env_cfg.py",
            "deploy/robots/g1_29dof/config/config.yaml",
            "deploy/robots/g1_29dof/config/policy/velocity/v0/params/deploy.yaml",
            "deploy/robots/g1_29dof/config/policy/velocity/v0/exported/policy.onnx",
        ],
    )
    archive = archive_probe(root / "source.tar.gz")
    if not archive["tar_valid"]:
        raise StagingError(f"Unitree source archive is not complete: {root / 'source.tar.gz'}")

    pin = {
        "schema": "embodied-source-pin/v1",
        "observed_at": observed_at,
        "repository": UNITREE_REPOSITORY,
        "commit": UNITREE_COMMIT,
        "source_form": "github_codeload_commit_archive",
        "source_tree": str(source),
        "full_source_snapshot_ready": True,
        "archive": archive,
        "required_static_files": [file_record(path, source) for path in required],
    }
    write_manifest(root / "PIN.json", pin)

    entrypoint = {
        "schema": "embodied-native-entrypoint/v1",
        "candidate_id": "unitree_rl_lab",
        "selected_track": "g1_29dof_velocity_locomotion_only",
        "entrypoint_defined": True,
        "commands": {
            "list": ["./unitree_rl_lab.sh", "-l"],
            "play": ["./unitree_rl_lab.sh", "-p", "--task", "Unitree-G1-29dof-Velocity"],
            "python_equivalent": ["python", "scripts/rsl_rl/play.py", "--task", "Unitree-G1-29dof-Velocity"],
        },
        "locally_executable": False,
        "role_boundary": "locomotion baseline only; not a manipulation expert",
        "blockers": ["Isaac Sim/Isaac Lab runtime not available in the audited interpreter", "external Unitree robot model directory not staged"],
    }
    write_manifest(root / "NATIVE_ENTRYPOINT.json", entrypoint)

    weights = model_manifest(source)
    velocity_relative = "deploy/robots/g1_29dof/config/policy/velocity/v0/exported/policy.onnx"
    selected = next((row for row in weights if row.get("relative_path") == velocity_relative), None)
    weight_manifest = {
        "schema": "embodied-weight-manifest/v1",
        "candidate_id": "unitree_rl_lab",
        "selected_variant": "g1_29dof_velocity_v0",
        "selected_weight_ready": bool(selected and not selected["pointer_only"]),
        "selected_weight": selected,
        "all_repository_model_files": weights,
        "license_status": "manual component review required",
    }
    write_manifest(root / "WEIGHTS.json", weight_manifest)

    environment = {
        "schema": "embodied-native-environment-lock/v1",
        "candidate_id": "unitree_rl_lab",
        "declared_versions": {"Isaac Sim": "5.1.0", "Isaac Lab": "2.3.0"},
        "ready_for_native_reproduction": False,
        "host_probe": host_probe(["isaaclab", "isaacsim", "torch", "gymnasium"], ["nvidia-smi", "cmake"]),
        "external_assets": {"unitree_model_or_unitree_ros_staged": False},
        "blockers": ["Isaac runtime not available in current interpreter", "external robot description required by upstream README is absent"],
    }
    write_manifest(root / "environment.lock.json", environment)

    licenses = {
        "schema": "embodied-component-license-evidence/v1",
        "candidate_id": "unitree_rl_lab",
        "legal_conclusion": False,
        "components": [
            {"scope": "source_and_repository_payload", **file_record(source / "LICENCE", source)},
            {"scope": "Isaac Lab", **file_record(source / "doc/licenses/isaaclab-license.txt", source)},
            {"scope": "ONNX Runtime", **file_record(source / "doc/licenses/onnxruntime-license.txt", source)},
            {"scope": "external_Unitree_robot_description", "status": "absent_unresolved", "manual_review_required": True},
            {"scope": "shipped_policy_weights", "status": "manual_scope_review_required", "manual_review_required": True},
        ],
        "distribution_status": "unresolved_internal_only",
    }
    write_manifest(root / "ASSET_LICENSES.json", licenses)

    joint_path = source / "source/unitree_rl_lab/unitree_rl_lab/assets/robots/unitree.py"
    joints = unitree_joint_names(joint_path)
    env_path = source / "source/unitree_rl_lab/unitree_rl_lab/tasks/locomotion/robots/g1/29dof/velocity_env_cfg.py"
    deploy_path = source / "deploy/robots/g1_29dof/config/policy/velocity/v0/params/deploy.yaml"
    env_text = env_path.read_text(encoding="utf-8")
    deploy_text = deploy_path.read_text(encoding="utf-8")
    contract = {
        "schema": "embodied-control-contract-evidence/v1",
        "candidate_id": "unitree_rl_lab",
        "identity": {"repository": UNITREE_REPOSITORY, "commit": UNITREE_COMMIT},
        "robot": {
            "model_dimensions": {"embodiment": "Unitree G1-29dof", "actuated_joint_count": len(joints)},
            "joint_and_actuator_order": {"joint_sdk_names": joints, "deploy_joint_ids_map_present": "joint_ids_map:" in deploy_text},
            "actuator_types_gains_limits": {
                "type": "Isaac Lab ImplicitActuatorCfg",
                "groups": ["N7520-14.3", "N7520-22.5", "N5020-16", "W4010-25"],
                "deploy_stiffness_and_damping_present": "stiffness:" in deploy_text and "damping:" in deploy_text,
            },
        },
        "simulation": {
            "engine_and_version": {"engine": "Isaac Sim / Isaac Lab", "Isaac Sim": "5.1.0", "Isaac Lab": "2.3.0"},
            "physics_timestep_s": 0.005,
            "solver_contact_friction": {
                "terrain_static_friction": 1.0,
                "terrain_dynamic_friction": 1.0,
                "robot_randomized_static_range": [0.3, 1.0],
                "robot_randomized_dynamic_range": [0.3, 1.0],
                "engine": "PhysX",
            },
        },
        "runtime": {"dependencies": {"required": ["Isaac Sim 5.1.0", "Isaac Lab 2.3.0"], "entrypoint": "unitree_rl_lab.sh"}},
        "policy": {
            "raw_interfaces": {
                "input": "ordered policy observations from deploy.yaml",
                "output": {"kind": "joint position action", "dimension": len(joints)},
                "weight_sha256": selected["sha256"] if selected else None,
            }
        },
        "observation": {
            "fields_order_units": {
                "order": ["base_ang_vel", "projected_gravity", "velocity_commands", "joint_pos_rel", "joint_vel_rel", "last_action"],
                "joint_position_unit": "rad",
                "joint_velocity_unit": "rad/s",
            },
            "normalization_and_history": {"history_length": 5, "scales_are_frozen_in": "deploy.yaml"},
        },
        "action": {
            "fields_order_units_bounds": {"order": joints, "unit": "normalized offset converted to rad", "scale": 0.25, "bounds": None},
            "duration_and_hold_semantics": {"step_dt_s": 0.02, "held_physics_steps": 4},
        },
        "control": {
            "physics_low_high_frequencies": {"physics_hz": 200, "policy_hz": 50},
            "native_transition_semantics": "Passive -> FixStand -> Velocity FSM; controller button transitions are in config.yaml",
        },
        "task": {
            "stage_and_transition_predicates": {"scope": "locomotion only", "terminations": ["time_out", "base_height < 0.2", "bad_orientation > 0.8 rad"]}
        },
        "hooks": {
            "privileged_contact_wbc_events": {"contact_sensor_history": 3, "critic_group_present": "class CriticCfg" in env_text},
            "checkpoint_and_replay": {"play_entrypoint": "scripts/rsl_rl/play.py", "export_formats": ["jit", "onnx"]},
        },
        "failure": {
            "stop_codes_and_taxonomy": ["time_out", "base_height", "bad_orientation"],
            "reset_and_recovery": ["reset_root_state_uniform", "reset_joints_by_scale", "Passive/FixStand FSM"],
        },
        "reproducibility": {
            "seeds_environment_command": {"train_seed_argument": "--seed", "task": "Unitree-G1-29dof-Velocity", "fixed_seed_selected": False}
        },
        "unknown_fields_block_adaptation": True,
        "evidence_files": [file_record(path, source) for path in required],
    }
    write_manifest(root / "CONTROL_CONTRACT.json", contract)
    return {"pin": pin, "entrypoint": entrypoint, "environment": environment, "contract": contract}


def stage_source_a(run_root: Path, source_a_run: Path, observed_at: str) -> dict[str, Any]:
    root = run_root / "staging" / "source_a_g1_manipulation"
    branch = source_a_run / "branches/A"
    source = branch / "source"
    source_contract_path = branch / "SOURCE_CONTRACT.json"
    required = require_files(source, ["run.py", "g1.xml", "model_config.json", "walker.onnx", "right_reacher.onnx"])
    source_contract = read_json(source_contract_path)
    config = read_json(source / "model_config.json")
    run_text = (source / "run.py").read_text(encoding="utf-8")
    contract = {
        "schema": "embodied-control-contract-evidence/v1",
        "candidate_id": "source_a_g1_manipulation",
        "identity": {"repository": source_contract["repo"], "commit": source_contract["commit"]},
        "robot": {
            "model_dimensions": source_contract["model"],
            "joint_and_actuator_order": {"joint_names": config["joint_names"], "measured_mapping": source_contract["joint_index_mapping"]},
            "actuator_types_gains_limits": {"control": "PD position target plus torque clipping", "action_scales": config["action_scales"], "implementation": "run.py::_compute_pd_gains"},
        },
        "simulation": {
            "engine_and_version": {"engine": "MuJoCo", "version": source_contract["environment"]["mujoco"]},
            "physics_timestep_s": source_contract["model"]["dt"],
            "solver_contact_friction": {"source": "g1.xml and scene.xml", "runtime_model_hash": source_contract["files"]["g1.xml"]},
        },
        "runtime": {"dependencies": source_contract["environment"]},
        "policy": {"raw_interfaces": source_contract["policy_interfaces"]},
        "observation": {
            "fields_order_units": {"walker_order": ["base_lin_vel", "base_ang_vel", "projected_gravity", "joint_pos", "joint_vel", "last_action", "velocity_command"], "walker_dimension": config["walker"]["input_dim"]},
            "normalization_and_history": {"walker_obs_mean": config["walker"]["obs_mean"], "walker_obs_std": config["walker"]["obs_std"], "history": "single frame"},
        },
        "action": {
            "fields_order_units_bounds": {"order": config["joint_names"], "unit": "normalized policy value scaled to rad target", "scales": config["action_scales"], "bounds": "velocity command bounds and reach bounds in run.py"},
            "duration_and_hold_semantics": {"physics_timestep_s": 0.005, "decimation": 4, "policy_hz": 50},
        },
        "control": {
            "physics_low_high_frequencies": {"physics_hz": 200, "policy_hz": 50},
            "native_transition_semantics": ["WALK", "REACH", "grip toggle", "manual stop", "space reset"],
        },
        "frames": {"world_base_task_camera": {"cameras": ["head_cam", "wrist_cam", "overhead"], "reach_target_frame": "pelvis-local implementation in run.py"}},
        "task": {"stage_and_transition_predicates": {"native_scope": "interactive walk/reach/grip; automated task predicates live in historical wrapper", "source_success_evidence": "jobs/A_native_02/RESULT.json"}},
        "hooks": {"policy_rgbd_proprio_action": {"head_and_wrist_rgb": True, "depth": False, "native_recording": False}},
        "failure": {"reset_and_recovery": {"space_reset": "mj_resetData plus action/mode reset", "automatic_recovery": False}},
        "reproducibility": {"seeds_environment_command": {"native_command": ["python", "run.py", "--no-cameras"], "seed_argument": False}},
        "unknown_fields_block_adaptation": True,
        "evidence_files": [file_record(source_contract_path), *[file_record(path, source) for path in required]],
        "static_markers": {"decimation_4": "decimation = 4" in run_text, "timestep_0_005": "model.opt.timestep = 0.005" in run_text},
    }
    root.mkdir(parents=True, exist_ok=True)
    write_manifest(root / "CONTROL_CONTRACT.json", contract)
    return {"contract": contract}


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--source-a-run", type=Path, default=DEFAULT_SOURCE_A_RUN)
    parser.add_argument("--observed-at")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    observed_at = args.observed_at or datetime.now(timezone.utc).isoformat()
    results = {
        "groot_wbc_sonic": stage_groot(args.run_root, observed_at),
        "unitree_rl_lab": stage_unitree(args.run_root, observed_at),
        "source_a_g1_manipulation": stage_source_a(args.run_root, args.source_a_run, observed_at),
    }
    print(
        json.dumps(
            {
                "run_root": str(args.run_root),
                "candidates": sorted(results),
                "physics_attempts": 0,
                "model_forwards": 0,
                "network_accessed_during_this_command": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
