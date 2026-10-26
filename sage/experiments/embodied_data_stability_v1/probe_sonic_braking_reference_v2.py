"""Counterfactual reference probe on frozen real states; never admission."""

import argparse
from pathlib import Path

from . import sonic_native_dynamic_shadow as native
from .audit_candidates import canonical_sha256, write_json_atomic
from .audit_sonic_supported_execution import read_bound_json
from .sonic_braking_reference import build_braking_reference, select_reference
from .sonic_native_full_shadow import _make_session
from .sonic_native_planner_preflight import _file_binding
from .sonic_reactive_stop_transition import build_stop_reference
from .sonic_semantic_shadow import (
    ENCODER_ASSEMBLER,
    DECODER_ASSEMBLER,
    body_joint_target_from_raw_action,
)
from .sonic_supported_shadow import official_decoder_blocks, last_action_rows


def run(output):
    import hashlib
    import numpy as np

    if output.exists():
        raise FileExistsError(output)
    root = native.DEFAULT_RUN_ROOT
    source = root / "reactive_stop_active_01/TRACE.json"
    trace = read_bound_json(source)
    rows = trace["records"]
    inputs = native._mapping_inputs(
        [r["actual_qpos"] for r in rows],
        [r["actual_qvel"] for r in rows],
        [r["actual_quaternion"] for r in rows],
        [r["actual_gyro"] for r in rows],
    )
    applied = np.asarray(
        [r["actual_command_raw_equivalent_isaaclab"] for r in rows], dtype=np.float32
    )
    planner = _make_session(
        native.DEFAULT_BUNDLE / "planner/target_vel/V2/planner_sonic.onnx"
    )
    original, original_vel = build_stop_reference(planner)
    conditions = [("original_idle", [(0, original, original_vel)])]
    metadata = {}
    for speed in (0.1, 0.15, 0.25):
        versions, info = build_braking_reference(planner, brake_speed=speed)
        name = f"brake_{speed}"
        conditions.append((name, versions))
        metadata[name] = info
    del planner
    encoder = _make_session(
        native.DEFAULT_BUNDLE / "policy/sonic_v1_1/model_encoder.onnx"
    )
    decoder = _make_session(
        native.DEFAULT_BUNDLE / "policy/sonic_v1_1/model_decoder.onnx"
    )
    result = []
    for name, versions in conditions:
        samples = []
        for index, row in enumerate(rows):
            frame = row["reference_tick"]
            if row["tick"] < 50 or frame < 40:
                continue
            ref, vel = select_reference(versions, frame)
            enc = np.asarray(
                [
                    ENCODER_ASSEMBLER.assemble(
                        native.build_dynamic_g1_encoder_blocks(
                            ref,
                            vel,
                            frame,
                            initial_robot_quaternion_wxyz=(1.0, 0.0, 0.0, 0.0),
                            current_robot_quaternion_wxyz=row["actual_quaternion"],
                        )
                    )
                ],
                dtype=np.float32,
            )
            token = encoder.run(None, {encoder.get_inputs()[0].name: enc})[0]
            dec = np.asarray(
                [
                    DECODER_ASSEMBLER.assemble(
                        official_decoder_blocks(
                            inputs,
                            index,
                            token,
                            last_action_rows(applied, index, legacy=False),
                        )
                    )
                ],
                dtype=np.float32,
            )
            raw = decoder.run(None, {decoder.get_inputs()[0].name: dec})[0].reshape(29)
            target = np.asarray(
                body_joint_target_from_raw_action(
                    raw, phase="braking_probe", sim_time_s=frame * 0.02
                ).position_target_rad
            )
            samples.append(
                {
                    "frame": frame,
                    "right_ankle_pitch_rad": float(target[10]),
                    "max_delta_from_executed_rad": float(
                        np.max(np.abs(target - row["candidate_rad"]))
                    ),
                    "encoder_matches_original": hashlib.sha256(
                        enc.tobytes()
                    ).hexdigest()
                    == row["encoder_input_sha256"],
                    "decoder_matches_original": hashlib.sha256(
                        dec.tobytes()
                    ).hexdigest()
                    == row["decoder_input_sha256"],
                    "max_future_joint_speed_rad_s": float(
                        np.max(np.abs(vel[frame : frame + 46]))
                    ),
                    "target": target.tolist(),
                }
            )
        result.append({"condition": name, "samples": samples})
    document = {
        "schema": "sonic-braking-reference-offline-probe/v2",
        "source_trace": _file_binding(source),
        "implementation": _file_binding(Path(__file__)),
        "reference_implementation": _file_binding(
            Path(__file__).with_name("sonic_braking_reference.py")
        ),
        "conditions": result,
        "planner": metadata,
        "physics_steps": 0,
        "admission_ready": False,
        "limitation": "counterfactual inputs on old real states, not closed-loop stability",
    }
    document["content_sha256_excluding_this_field"] = canonical_sha256(document)
    write_json_atomic(output, document)
    for condition in result:
        samples = condition["samples"]
        print(
            condition["condition"],
            "max right ankle",
            max(s["right_ankle_pitch_rad"] for s in samples),
            "original exact",
            all(
                s["encoder_matches_original"]
                and s["decoder_matches_original"]
                and s["max_delta_from_executed_rad"] == 0
                for s in samples
            ),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
