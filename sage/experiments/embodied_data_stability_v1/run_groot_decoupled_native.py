"""Run one bounded GR00T Decoupled-WBC native MuJoCo reproduction.

This S1 runner reuses the pinned upstream MJCF, YAML, observation construction,
PD loop, and unmodified Balance/Walk ONNX weights.  It removes only interactive
keyboard/viewer plumbing so the frozen stand/walk/stop protocol can run
headlessly.  It is evidence for native controller capability, not a production
data generator or a SONIC-v1.1 reproduction.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Iterable

from .audit_candidates import write_json_atomic


GROOT_COMMIT = "b042411fae38ee4d1af9aac82a37a1f8d14d6dd0"
DEFAULT_S0_ROOT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_s0_20261014_v1"
)
DEFAULT_HANDOFF_ROOT = Path(
    "/data/wsj/main/scene_handoffs/"
    "embodied_dual_end_effector_audit_20260925_v1/sources/groot"
)
DEFAULT_PRIOR_CONTROL_ROOT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_dual_control_20260925_v1"
)

EXPECTED_RUNTIME = {
    "numpy": "1.26.4",
    "mujoco": "3.3.2",
    "onnxruntime": "1.22.1",
}

PHASES = (
    {"name": "stand_settle", "duration_seconds": 2.0, "loco_cmd": (0.0, 0.0, 0.0)},
    {"name": "forward_walk", "duration_seconds": 4.0, "loco_cmd": (0.2, 0.0, 0.0)},
    {"name": "stand_stop", "duration_seconds": 4.0, "loco_cmd": (0.0, 0.0, 0.0)},
)

# Frozen before the first execution.  These gates only test the native
# stand/walk/stop component; they are not production trajectory quality gates.
GATES = {
    "min_pelvis_height_m": 0.45,
    "max_tilt_rad": 0.65,
    "min_forward_walk_displacement_m": 0.10,
    "max_abs_lateral_displacement_m": 0.25,
    "max_stop_tail_linear_speed_mps": 0.20,
    "stop_tail_seconds": 1.0,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def parse_lfs_pointer(path: Path) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("oid sha256:"):
            fields["oid_sha256"] = line.removeprefix("oid sha256:")
        elif line.startswith("size "):
            fields["size_bytes"] = int(line.removeprefix("size "))
    if set(fields) != {"oid_sha256", "size_bytes"}:
        raise ValueError(f"invalid Git-LFS pointer: {path}")
    return fields


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def phase_at(sim_time: float) -> dict[str, Any]:
    boundary = 0.0
    for phase in PHASES:
        boundary += float(phase["duration_seconds"])
        if sim_time < boundary - 1e-12:
            return phase
    return PHASES[-1]


def onnx_shape_matches(actual: list[Any], feature_count: int) -> bool:
    """Accept a fixed or symbolic batch dimension with a fixed feature width."""
    return len(actual) == 2 and (actual[0] in (1, None) or isinstance(actual[0], str)) and actual[1] == feature_count


def quat_rotate_inverse(q: Any, v: Any, np: Any) -> Any:
    """Exact NumPy equation used by the pinned upstream native script."""
    w, x, y, z = q
    q_conj = np.array([w, -x, -y, -z])
    return np.array(
        [
            v[0] * (q_conj[0] ** 2 + q_conj[1] ** 2 - q_conj[2] ** 2 - q_conj[3] ** 2)
            + v[1] * 2 * (q_conj[1] * q_conj[2] - q_conj[0] * q_conj[3])
            + v[2] * 2 * (q_conj[1] * q_conj[3] + q_conj[0] * q_conj[2]),
            v[0] * 2 * (q_conj[1] * q_conj[2] + q_conj[0] * q_conj[3])
            + v[1] * (q_conj[0] ** 2 - q_conj[1] ** 2 + q_conj[2] ** 2 - q_conj[3] ** 2)
            + v[2] * 2 * (q_conj[2] * q_conj[3] - q_conj[0] * q_conj[1]),
            v[0] * 2 * (q_conj[1] * q_conj[3] - q_conj[0] * q_conj[2])
            + v[1] * 2 * (q_conj[2] * q_conj[3] + q_conj[0] * q_conj[1])
            + v[2] * (q_conj[0] ** 2 - q_conj[1] ** 2 - q_conj[2] ** 2 + q_conj[3] ** 2),
        ]
    )


def compute_observation(
    data: Any,
    config: dict[str, Any],
    action: Any,
    loco_cmd: Any,
    n_joints: int,
    np: Any,
) -> Any:
    """Reproduce the selected pinned upstream script's 86-value observation."""
    command = np.zeros(7, dtype=np.float32)
    command[:3] = loco_cmd[:3] * config["cmd_scale"]
    command[3] = config["height_cmd"]
    command[4:7] = config["rpy_cmd"]
    qj = data.qpos[7 : 7 + n_joints].copy()
    dqj = data.qvel[6 : 6 + n_joints].copy()
    quat = data.qpos[3:7].copy()
    omega = data.qvel[3:6].copy()
    padded_defaults = np.zeros(n_joints, dtype=np.float32)
    count = min(len(config["default_angles"]), n_joints)
    padded_defaults[:count] = config["default_angles"][:count]
    qj_scaled = (qj - padded_defaults) * config["dof_pos_scale"]
    dqj_scaled = dqj * config["dof_vel_scale"]
    gravity_orientation = quat_rotate_inverse(quat, np.array([0.0, 0.0, -1.0]), np)
    omega_scaled = omega * config["ang_vel_scale"]
    single_obs = np.zeros(86, dtype=np.float32)
    single_obs[0:7] = command
    single_obs[7:10] = omega_scaled
    single_obs[10:13] = gravity_orientation
    single_obs[13 : 13 + n_joints] = qj_scaled
    single_obs[13 + n_joints : 13 + 2 * n_joints] = dqj_scaled
    single_obs[13 + 2 * n_joints : 13 + 2 * n_joints + 15] = action
    return single_obs


def _require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def verify_inputs(
    s0_root: Path,
    handoff_root: Path,
    prior_control_root: Path,
) -> dict[str, Any]:
    stage = s0_root / "staging" / "groot_wbc_sonic"
    source = stage / "source"
    native_root = source / "decoupled_wbc" / "sim2mujoco"
    source_pin = read_json(_require_file(stage / "PIN.json"))
    media_pin = read_json(_require_file(handoff_root / "PIN.json"))
    if source_pin.get("commit") != GROOT_COMMIT or media_pin.get("commit") != GROOT_COMMIT:
        raise RuntimeError("GR00T source/media commit mismatch")

    script = _require_file(native_root / "scripts" / "run_mujoco_gear_wbc.py")
    yaml_path = _require_file(native_root / "resources" / "robots" / "g1" / "g1_gear_wbc.yaml")
    xml_path = _require_file(native_root / "resources" / "robots" / "g1" / "g1_gear_wbc.xml")
    pointer_dir = native_root / "resources" / "robots" / "g1" / "policy"
    balance_pointer = _require_file(pointer_dir / "GR00T-WholeBodyControl-Balance.onnx")
    walk_pointer = _require_file(pointer_dir / "GR00T-WholeBodyControl-Walk.onnx")
    media = handoff_root / "media" / "decoupled_wbc"
    balance = _require_file(
        media / "sim2mujoco" / "resources" / "robots" / "g1" / "policy"
        / "GR00T-WholeBodyControl-Balance.onnx"
    )
    walk = _require_file(
        prior_control_root / "sources" / "media" / "sim2mujoco" / "resources" / "robots"
        / "g1" / "policy" / "GR00T-WholeBodyControl-Walk.onnx"
    )
    mesh_root = media / "control" / "robot_model" / "model_data" / "g1" / "meshes"
    mesh_files = sorted(mesh_root.glob("*.STL"))
    if not mesh_files:
        raise RuntimeError("no pinned G1 mesh files found")

    weight_rows = []
    for role, pointer, weight in (
        ("balance", balance_pointer, balance),
        ("walk", walk_pointer, walk),
    ):
        expected = parse_lfs_pointer(pointer)
        actual = file_record(weight)
        matches = (
            expected["oid_sha256"] == actual["sha256"]
            and expected["size_bytes"] == actual["size_bytes"]
        )
        weight_rows.append(
            {
                "role": role,
                "pointer": file_record(pointer),
                "lfs_object": actual,
                "declared_lfs": expected,
                "matches_lfs_pointer": matches,
            }
        )
    if not all(row["matches_lfs_pointer"] for row in weight_rows):
        raise RuntimeError("GR00T ONNX byte identity does not match pinned LFS pointers")

    return {
        "source_root": source,
        "native_root": native_root,
        "script": script,
        "yaml": yaml_path,
        "xml": xml_path,
        "mesh_root": mesh_root,
        "balance": balance,
        "walk": walk,
        "manifest": {
            "repository": "NVlabs/GR00T-WholeBodyControl",
            "commit": GROOT_COMMIT,
            "track": "decoupled_wbc_sim2mujoco",
            "track_boundary": (
                "GR00T family comparator; distinct from the selected SONIC-v1.1 track"
            ),
            "source_files": [file_record(path) for path in (script, yaml_path, xml_path)],
            "weights": weight_rows,
            "meshes": {
                "root": str(mesh_root),
                "file_count": len(mesh_files),
                "total_bytes": sum(path.stat().st_size for path in mesh_files),
                "aggregate_sha256": hashlib.sha256(
                    "".join(f"{path.name}:{sha256_file(path)}\n" for path in mesh_files).encode()
                ).hexdigest(),
            },
        },
    }


def prepare_runtime_assets(output_dir: Path, inputs: dict[str, Any]) -> Path:
    assets = output_dir / "runtime_assets"
    assets.mkdir()
    shutil.copy2(inputs["xml"], assets / "g1_gear_wbc.xml")
    os.symlink(inputs["mesh_root"], assets / "meshes", target_is_directory=True)
    return assets


def load_config(path: Path, yaml: Any, np: Any) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("kps", "kds", "default_angles", "cmd_scale", "cmd_init", "rpy_cmd"):
        config[key] = np.asarray(config[key], dtype=np.float32)
    return config


def run_attempt(
    output_dir: Path,
    s0_root: Path,
    handoff_root: Path,
    prior_control_root: Path,
    seed: int,
) -> dict[str, Any]:
    started = time.monotonic()
    inputs = verify_inputs(s0_root, handoff_root, prior_control_root)
    manifest = {
        "schema": "embodied-s1-native-attempt-manifest/v1",
        "candidate_id": "groot_decoupled_wbc",
        **inputs["manifest"],
        "seed": seed,
        "protocol": {"phases": PHASES, "gates": GATES},
        "rendering": False,
        "training": False,
        "manual_interventions": 0,
        "upstream_delta": (
            "Interactive keyboard/viewer and real-time sleep removed; native observation, "
            "policy selection, action scaling, PD gains, decimation, MJCF, and weights retained."
        ),
    }
    write_json_atomic(output_dir / "RUN_MANIFEST.json", manifest)

    import mujoco
    import numpy as np
    import onnxruntime as ort
    import yaml

    versions = {
        "numpy": np.__version__,
        "mujoco": mujoco.__version__,
        "onnxruntime": ort.__version__,
        "pyyaml": yaml.__version__,
    }
    mismatches = {
        name: {"expected": expected, "actual": versions.get(name)}
        for name, expected in EXPECTED_RUNTIME.items()
        if versions.get(name) != expected
    }
    providers = ort.get_available_providers()
    preflight = {
        "schema": "embodied-s1-native-preflight/v1",
        "runtime_versions": versions,
        "expected_runtime": EXPECTED_RUNTIME,
        "runtime_contract_matches": not mismatches,
        "mismatches": mismatches,
        "available_onnx_providers": providers,
        "selected_onnx_providers": ["CPUExecutionProvider"],
    }
    write_json_atomic(output_dir / "PREFLIGHT.json", preflight)
    if mismatches:
        raise RuntimeError(f"runtime contract mismatch: {mismatches}")
    if "CPUExecutionProvider" not in providers:
        raise RuntimeError("ONNX Runtime CPUExecutionProvider is unavailable")

    np.random.seed(seed)
    runtime_assets = prepare_runtime_assets(output_dir, inputs)
    config = load_config(inputs["yaml"], yaml, np)
    model = mujoco.MjModel.from_xml_path(str(runtime_assets / "g1_gear_wbc.xml"))
    data = mujoco.MjData(model)
    model.opt.timestep = float(config["simulation_dt"])
    n_joints = int(data.qpos.shape[0] - 7)
    if (model.nq, model.nv, model.nu, n_joints) != (36, 35, 29, 29):
        raise RuntimeError(
            f"unexpected native model dimensions: {(model.nq, model.nv, model.nu, n_joints)}"
        )
    if config["num_actions"] != 15 or config["num_obs"] != 516:
        raise RuntimeError("unexpected pinned policy dimensions")

    session_options = ort.SessionOptions()
    session_options.intra_op_num_threads = 1
    session_options.inter_op_num_threads = 1
    balance = ort.InferenceSession(
        str(inputs["balance"]), sess_options=session_options, providers=["CPUExecutionProvider"]
    )
    walk = ort.InferenceSession(
        str(inputs["walk"]), sess_options=session_options, providers=["CPUExecutionProvider"]
    )
    session_shapes = {}
    for name, session in (("balance", balance), ("walk", walk)):
        input_meta, output_meta = session.get_inputs()[0], session.get_outputs()[0]
        session_shapes[name] = {
            "input_name": input_meta.name,
            "input_shape": input_meta.shape,
            "input_type": input_meta.type,
            "output_name": output_meta.name,
            "output_shape": output_meta.shape,
            "output_type": output_meta.type,
        }
        if not onnx_shape_matches(input_meta.shape, 516) or not onnx_shape_matches(
            output_meta.shape, 15
        ):
            raise RuntimeError(f"unexpected {name} ONNX interface: {session_shapes[name]}")

    action = np.zeros(config["num_actions"], dtype=np.float32)
    target_dof_pos = config["default_angles"].copy()
    history = collections.deque(
        [np.zeros(86, dtype=np.float32)] * int(config["obs_history_len"]),
        maxlen=int(config["obs_history_len"]),
    )
    obs = np.zeros(config["num_obs"], dtype=np.float32)
    pelvis_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
    if pelvis_id < 0:
        raise RuntimeError("pelvis body missing")
    mujoco.mj_forward(model, data)
    initial_xy = data.xpos[pelvis_id, :2].copy()
    phase_starts = {PHASES[0]["name"]: data.xpos[pelvis_id].copy()}
    policy_calls = {"balance": 0, "walk": 0}
    phase_policy_calls = {phase["name"]: 0 for phase in PHASES}
    counters = {
        "physics_steps": 0,
        "nonfinite_steps": 0,
        "external_wrench_violations": 0,
        "max_penetration_m": 0.0,
        "max_contact_force_n": 0.0,
        "min_pelvis_height_m": float("inf"),
        "max_tilt_rad": 0.0,
        "max_abs_lateral_displacement_m": 0.0,
    }
    samples: dict[str, list[Any]] = {
        name: []
        for name in ("time", "phase", "command", "qpos", "qvel", "action", "target", "pelvis")
    }
    total_seconds = sum(float(phase["duration_seconds"]) for phase in PHASES)
    total_steps = round(total_seconds / model.opt.timestep)
    if abs(total_steps * model.opt.timestep - total_seconds) > 1e-9:
        raise RuntimeError("protocol phase duration is not divisible by native simulation dt")
    warning_start = data.warning.number.copy()
    walk_start_x = None
    walk_end_x = None
    stop_tail_speeds: list[float] = []

    for step in range(total_steps):
        phase = phase_at(float(data.time))
        if phase["name"] not in phase_starts:
            phase_starts[phase["name"]] = data.xpos[pelvis_id].copy()
        loco_cmd = np.asarray(phase["loco_cmd"], dtype=np.float32)
        if phase["name"] == "forward_walk" and walk_start_x is None:
            walk_start_x = float(data.xpos[pelvis_id, 0])
        if phase["name"] == "stand_stop" and walk_end_x is None:
            walk_end_x = float(data.xpos[pelvis_id, 0])

        leg_tau = (
            (target_dof_pos - data.qpos[7 : 7 + config["num_actions"]]) * config["kps"]
            - data.qvel[6 : 6 + config["num_actions"]] * config["kds"]
        )
        data.ctrl[: config["num_actions"]] = leg_tau
        remaining = n_joints - config["num_actions"]
        if remaining:
            data.ctrl[config["num_actions"] :] = (
                -data.qpos[7 + config["num_actions"] : 7 + n_joints] * 100.0
                - data.qvel[6 + config["num_actions"] : 6 + n_joints] * 0.5
            )
        if np.any(data.qfrc_applied) or np.any(data.xfrc_applied):
            counters["external_wrench_violations"] += 1
        mujoco.mj_step(model, data)
        counters["physics_steps"] += 1
        if not (
            np.isfinite(data.qpos).all()
            and np.isfinite(data.qvel).all()
            and np.isfinite(data.ctrl).all()
        ):
            counters["nonfinite_steps"] += 1
            break
        height = float(data.xpos[pelvis_id, 2])
        tilt = float(np.arccos(np.clip(data.xmat[pelvis_id].reshape(3, 3)[2, 2], -1.0, 1.0)))
        counters["min_pelvis_height_m"] = min(counters["min_pelvis_height_m"], height)
        counters["max_tilt_rad"] = max(counters["max_tilt_rad"], tilt)
        counters["max_abs_lateral_displacement_m"] = max(
            counters["max_abs_lateral_displacement_m"],
            abs(float(data.xpos[pelvis_id, 1] - initial_xy[1])),
        )
        for contact_index in range(data.ncon):
            contact = data.contact[contact_index]
            force = np.zeros(6)
            mujoco.mj_contactForce(model, data, contact_index, force)
            counters["max_penetration_m"] = max(
                counters["max_penetration_m"], max(0.0, -float(contact.dist))
            )
            counters["max_contact_force_n"] = max(
                counters["max_contact_force_n"], float(np.linalg.norm(force[:3]))
            )
        if data.time >= total_seconds - GATES["stop_tail_seconds"] - 1e-9:
            stop_tail_speeds.append(float(np.linalg.norm(data.qvel[:3])))

        if (step + 1) % int(config["control_decimation"]) == 0:
            single_obs = compute_observation(data, config, action, loco_cmd, n_joints, np)
            history.append(single_obs)
            for index, item in enumerate(history):
                obs[index * 86 : (index + 1) * 86] = item
            session_name = "balance" if np.linalg.norm(loco_cmd) <= 0.05 else "walk"
            session = balance if session_name == "balance" else walk
            input_name = session.get_inputs()[0].name
            action = session.run(None, {input_name: obs[None, :]})[0].squeeze().astype(np.float32)
            target_dof_pos = action * config["action_scale"] + config["default_angles"]
            policy_calls[session_name] += 1
            phase_policy_calls[phase["name"]] += 1
            samples["time"].append(float(data.time))
            samples["phase"].append(tuple(row["name"] for row in PHASES).index(phase["name"]))
            samples["command"].append(loco_cmd.copy())
            samples["qpos"].append(data.qpos.copy())
            samples["qvel"].append(data.qvel.copy())
            samples["action"].append(action.copy())
            samples["target"].append(target_dof_pos.copy())
            samples["pelvis"].append(data.xpos[pelvis_id].copy())

    final_pelvis = data.xpos[pelvis_id].copy()
    if walk_start_x is None or walk_end_x is None:
        raise RuntimeError("protocol did not enter all phases")
    forward_walk_displacement = walk_end_x - walk_start_x
    max_stop_tail_speed = max(stop_tail_speeds, default=float("inf"))
    warning_changed = bool(np.any(data.warning.number != warning_start))
    gate_results = {
        "completed_all_steps": counters["physics_steps"] == total_steps,
        "finite": counters["nonfinite_steps"] == 0,
        "no_external_wrench": counters["external_wrench_violations"] == 0,
        "used_balance_weight": policy_calls["balance"] > 0,
        "used_walk_weight": policy_calls["walk"] > 0,
        "all_phases_inferred": all(value > 0 for value in phase_policy_calls.values()),
        "pelvis_height": counters["min_pelvis_height_m"] >= GATES["min_pelvis_height_m"],
        "tilt": counters["max_tilt_rad"] <= GATES["max_tilt_rad"],
        "forward_progress": forward_walk_displacement >= GATES["min_forward_walk_displacement_m"],
        "lateral_drift": (
            counters["max_abs_lateral_displacement_m"]
            <= GATES["max_abs_lateral_displacement_m"]
        ),
        "stopped": max_stop_tail_speed <= GATES["max_stop_tail_linear_speed_mps"],
        "no_mujoco_warning": not warning_changed,
    }
    native_reproduction_passed = all(gate_results.values())
    np.savez_compressed(
        output_dir / "CONTROL_TICKS.npz",
        **{name: np.asarray(values) for name, values in samples.items()},
    )
    report = {
        "schema": "embodied-s1-native-attempt-result/v1",
        "candidate_id": "groot_decoupled_wbc",
        "track": "decoupled_wbc_sim2mujoco",
        "native_reproduction_passed": native_reproduction_passed,
        "gate_results": gate_results,
        "runtime_versions": versions,
        "onnx_interfaces": session_shapes,
        "metrics": {
            **counters,
            "policy_forwards": sum(policy_calls.values()),
            "policy_calls_by_weight": policy_calls,
            "phase_policy_calls": phase_policy_calls,
            "sim_seconds": float(data.time),
            "initial_pelvis_position": phase_starts[PHASES[0]["name"]].tolist(),
            "final_pelvis_position": final_pelvis.tolist(),
            "forward_walk_displacement_m": forward_walk_displacement,
            "max_stop_tail_linear_speed_mps": max_stop_tail_speed,
            "mujoco_warning_changed": warning_changed,
            "model_dimensions": {
                "nq": model.nq,
                "nv": model.nv,
                "nu": model.nu,
                "dt": model.opt.timestep,
            },
        },
        "artifacts": {
            "control_ticks": "CONTROL_TICKS.npz",
            "control_tick_count": len(samples["time"]),
        },
        "wall_seconds": time.monotonic() - started,
        "render_passes": 0,
        "training_updates": 0,
        "manual_interventions": 0,
        "production_accepted": False,
        "learning_validated": False,
        "quality_boundary": (
            "This is a GR00T Decoupled-WBC component reproduction, not SONIC-v1.1, "
            "a manipulation episode, or production-data acceptance."
        ),
    }
    write_json_atomic(output_dir / "RESULT.json", report)
    return report


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--s0-root", type=Path, default=DEFAULT_S0_ROOT)
    parser.add_argument("--handoff-root", type=Path, default=DEFAULT_HANDOFF_ROOT)
    parser.add_argument("--prior-control-root", type=Path, default=DEFAULT_PRIOR_CONTROL_ROOT)
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    try:
        result = run_attempt(
            args.output_dir,
            args.s0_root,
            args.handoff_root,
            args.prior_control_root,
            args.seed,
        )
    except BaseException:
        error = traceback.format_exc()
        write_json_atomic(
            args.output_dir / "RUNNER_FAILURE.json",
            {
                "schema": "embodied-s1-runner-failure/v1",
                "candidate_id": "groot_decoupled_wbc",
                "error": error,
                "production_accepted": False,
            },
        )
        print(error, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "native_reproduction_passed": result["native_reproduction_passed"],
                "physics_steps": result["metrics"]["physics_steps"],
                "policy_forwards": result["metrics"]["policy_forwards"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["native_reproduction_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
