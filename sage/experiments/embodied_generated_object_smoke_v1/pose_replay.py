"""Recompute contacts at every recorded v4 pose without advancing physics."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .common import BASE_RUN, RUN_ROOT, sha256, write_json


def _label(model: Any, mujoco: Any, geom_id: int) -> str:
    geom = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
    body_id = int(model.geom_bodyid[geom_id])
    body = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body_id)
    return geom or body or f"geom_{geom_id}"


def _contacts(model: Any, data: Any, mujoco: Any, red_body_id: int) -> dict:
    peak_all = 0.0
    peak_red = 0.0
    pair_all = None
    pair_red = None
    for contact in data.contact:
        penetration = max(0.0, -float(contact.dist))
        pair = " <-> ".join(
            sorted(
                (
                    _label(model, mujoco, int(contact.geom1)),
                    _label(model, mujoco, int(contact.geom2)),
                )
            )
        )
        if penetration > peak_all:
            peak_all, pair_all = penetration, pair
        if red_body_id in {
            int(model.geom_bodyid[int(contact.geom1)]),
            int(model.geom_bodyid[int(contact.geom2)]),
        } and penetration > peak_red:
            peak_red, pair_red = penetration, pair
    return {
        "all_penetration_m": peak_all,
        "all_pair": pair_all,
        "red_penetration_m": peak_red,
        "red_pair": pair_red,
        "contact_count": int(data.ncon),
    }


def replay(run_root: Path) -> dict:
    import mujoco

    state_path = BASE_RUN / "trajectory_01/state_stream/privileged_state.npz"
    with np.load(state_path, allow_pickle=False) as archive:
        times = archive["sim_time_s"].copy()
        qpos = archive["qpos"].copy()
        qvel = archive["qvel"].copy()
        ctrl = archive["ctrl"].copy()
    paths = {
        "base_v4_original_analytic_cylinder": BASE_RUN / "model/MODEL.xml",
        "generated_object_mesh": run_root / "model/MODEL.xml",
    }
    models = {key: mujoco.MjModel.from_xml_path(str(path)) for key, path in paths.items()}
    if len({(model.nq, model.nv, model.nu) for model in models.values()}) != 1:
        raise RuntimeError("pose replay models have different state dimensions")
    summaries: dict[str, Any] = {}
    traces: dict[str, Any] = {}
    for key, model in models.items():
        data = mujoco.MjData(model)
        red_body_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_BODY, "red_block"
        )
        red_penetration = np.zeros(len(times), dtype=np.float64)
        all_penetration = np.zeros(len(times), dtype=np.float64)
        red_pairs: list[str | None] = []
        all_pairs: list[str | None] = []
        contact_count = np.zeros(len(times), dtype=np.int64)
        for index in range(len(times)):
            data.qpos[:] = qpos[index]
            data.qvel[:] = qvel[index]
            data.ctrl[:] = ctrl[index]
            data.time = float(times[index])
            mujoco.mj_forward(model, data)
            row = _contacts(model, data, mujoco, red_body_id)
            red_penetration[index] = row["red_penetration_m"]
            all_penetration[index] = row["all_penetration_m"]
            red_pairs.append(row["red_pair"])
            all_pairs.append(row["all_pair"])
            contact_count[index] = row["contact_count"]
        red_peak = int(np.argmax(red_penetration))
        all_peak = int(np.argmax(all_penetration))
        summaries[key] = {
            "model_path": str(paths[key]),
            "model_sha256": sha256(paths[key]),
            "red_object_peak_penetration_m": float(red_penetration[red_peak]),
            "red_object_peak_time_s": float(times[red_peak]),
            "red_object_peak_pair": red_pairs[red_peak],
            "all_contact_peak_penetration_m": float(all_penetration[all_peak]),
            "all_contact_peak_time_s": float(times[all_peak]),
            "all_contact_peak_pair": all_pairs[all_peak],
            "samples_above_2mm": int(np.count_nonzero(red_penetration > 0.002)),
            "samples_above_10mm": int(np.count_nonzero(red_penetration > 0.010)),
            "sample_count": int(len(times)),
        }
        traces[key] = {
            "red_penetration_m": red_penetration,
            "all_penetration_m": all_penetration,
            "contact_count": contact_count,
        }
    output = run_root / "pose_replay"
    output.mkdir(exist_ok=False)
    np.savez_compressed(output / "CONTACT_TRACE.npz", sim_time_s=times, **{
        f"{key}__{field}": value
        for key, trace in traces.items()
        for field, value in trace.items()
    })
    base = summaries["base_v4_original_analytic_cylinder"]
    generated = summaries["generated_object_mesh"]
    report = {
        "schema": "embodied-generated-red-cylinder-pose-contact-replay/v1",
        "physics_advanced": False,
        "source_state": str(state_path),
        "source_state_sha256": sha256(state_path),
        "summaries": summaries,
        "generated_minus_base_red_peak_penetration_m": (
            generated["red_object_peak_penetration_m"]
            - base["red_object_peak_penetration_m"]
        ),
        "trace": str(output / "CONTACT_TRACE.npz"),
        "trace_sha256": sha256(output / "CONTACT_TRACE.npz"),
        "interpretation": (
            "This is a same-qpos geometric contact counterfactual. It does not predict "
            "controller adaptation or contact forces; the one authorized dynamic rollout "
            "is still required for the causal task comparison."
        ),
        "physics_steps": 0,
    }
    write_json(output / "RESULT.json", report)
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    args = parser.parse_args(argv)
    print(replay(args.run_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

