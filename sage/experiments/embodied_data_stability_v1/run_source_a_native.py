"""Run one bounded, headless Source-A native reproduction attempt.

This is an S1 evidence runner, not a production data generator.  It preserves
the pinned native source and weights, fixes one seed/case, disables rendering,
counts actual physics and policy calls, and writes a compact result.  Resource
containment (CPU, memory, and wall time) is supplied by the caller.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Iterable

from .audit_candidates import write_json_atomic
from .contact_diagnostics import CategorizedContactAudit


DEFAULT_SOURCE_A_RUN = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_stretch_ai_admission_20260926_v1/full_body_milestone/"
    "feasibility_guard_v4/prepared/payload_data_20261009/"
    "native_parallel_12h_20261011"
)


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


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        return json_safe(value.tolist())
    if hasattr(value, "item"):
        return json_safe(value.item())
    return str(value)


class NativeCounters:
    """Observation-only hooks for the candidate's real substeps and ONNX calls."""

    def __init__(
        self,
        mujoco: Any,
        ort: Any,
        max_physics_steps: int,
        max_sim_seconds: float,
        on_step: Any | None = None,
    ):
        self.mujoco = mujoco
        self.ort = ort
        self.max_physics_steps = max_physics_steps
        self.max_sim_seconds = max_sim_seconds
        self.physics_steps = 0
        self.policy_forwards = 0
        self.max_penetration_m = 0.0
        self.max_contact_force_n = 0.0
        self.external_wrench_violations = 0
        self.state_continuity_violations = 0
        self.nonfinite_steps = 0
        self.contact_audit = CategorizedContactAudit()
        self.model_dimensions: dict[str, Any] | None = None
        self._last_state: tuple[Any, Any, float] | None = None
        self._model: Any | None = None
        self._data: Any | None = None
        self._old_step = mujoco.mj_step
        self._old_run = ort.InferenceSession.run
        self._on_step = on_step

    def install(self) -> None:
        counters = self

        def step(model: Any, data: Any, *args: Any, **kwargs: Any) -> None:
            if args or kwargs:
                raise RuntimeError("native audit expects one unqualified MuJoCo substep per call")
            if counters._model is None:
                counters._model, counters._data = model, data
                counters.model_dimensions = {
                    "nq": int(model.nq),
                    "nv": int(model.nv),
                    "nu": int(model.nu),
                    "dt": float(model.opt.timestep),
                    "integrator": int(model.opt.integrator),
                    "body_count": int(model.nbody),
                }
            elif model is not counters._model or data is not counters._data:
                raise RuntimeError("secondary dynamic rollout detected")
            if counters.physics_steps >= counters.max_physics_steps:
                raise RuntimeError("physics step budget exhausted")
            if float(data.time + model.opt.timestep) > counters.max_sim_seconds + 1e-9:
                raise RuntimeError("simulation-time budget exhausted")
            if counters._last_state is not None:
                qpos, qvel, previous_time = counters._last_state
                if not (
                    counters._np.array_equal(data.qpos, qpos)
                    and counters._np.array_equal(data.qvel, qvel)
                    and float(data.time) == previous_time
                ):
                    counters.state_continuity_violations += 1
            if counters._np.any(data.qfrc_applied) or counters._np.any(data.xfrc_applied):
                counters.external_wrench_violations += 1
            counters._old_step(model, data)
            counters.physics_steps += 1
            counters._last_state = (data.qpos.copy(), data.qvel.copy(), float(data.time))
            if not (
                counters._np.isfinite(data.qpos).all()
                and counters._np.isfinite(data.qvel).all()
                and counters._np.isfinite(data.ctrl).all()
            ):
                counters.nonfinite_steps += 1
            for index, contact in enumerate(data.contact):
                force = counters._np.zeros(6)
                counters.mujoco.mj_contactForce(model, data, index, force)
                force_n = float(counters._np.linalg.norm(force[:3]))
                counters.max_penetration_m = max(counters.max_penetration_m, -float(contact.dist))
                counters.max_contact_force_n = max(
                    counters.max_contact_force_n,
                    force_n,
                )
                body_a = counters.mujoco.mj_id2name(
                    model,
                    counters.mujoco.mjtObj.mjOBJ_BODY,
                    int(model.geom_bodyid[contact.geom1]),
                ) or "world"
                body_b = counters.mujoco.mj_id2name(
                    model,
                    counters.mujoco.mjtObj.mjOBJ_BODY,
                    int(model.geom_bodyid[contact.geom2]),
                ) or "world"
                geom_a = counters.mujoco.mj_id2name(
                    model, counters.mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom1)
                ) or f"geom_{int(contact.geom1)}"
                geom_b = counters.mujoco.mj_id2name(
                    model, counters.mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom2)
                ) or f"geom_{int(contact.geom2)}"
                counters.contact_audit.observe(
                    step=counters.physics_steps,
                    sim_time_s=float(data.time),
                    body_a=body_a,
                    body_b=body_b,
                    geom_a=geom_a,
                    geom_b=geom_b,
                    distance_m=float(contact.dist),
                    force_n=force_n,
                )
            if counters._on_step is not None:
                counters._on_step(model, data, counters.physics_steps, counters.mujoco)

        def run(session: Any, output_names: Any, input_feed: Any, *args: Any, **kwargs: Any) -> Any:
            counters.policy_forwards += 1
            return counters._old_run(session, output_names, input_feed, *args, **kwargs)

        import numpy as np

        self._np = np
        self.mujoco.mj_step = step
        self.ort.InferenceSession.run = run

    def close(self) -> dict[str, Any]:
        self.mujoco.mj_step = self._old_step
        self.ort.InferenceSession.run = self._old_run
        return {
            "physics_steps": self.physics_steps,
            "policy_forwards": self.policy_forwards,
            "max_penetration_m": self.max_penetration_m,
            "max_contact_force_n": self.max_contact_force_n,
            "external_wrench_violations": self.external_wrench_violations,
            "state_continuity_violations": self.state_continuity_violations,
            "nonfinite_steps": self.nonfinite_steps,
            "model_dimensions": self.model_dimensions,
            "contact_categories": self.contact_audit.report(),
        }


def verify_source_contract(source: Path, contract: dict[str, Any]) -> dict[str, Any]:
    selected = [
        "run.py",
        "g1.xml",
        "model_config.json",
        "walker.onnx",
        "walker.onnx.data",
        "right_reacher.onnx",
    ]
    rows = []
    for relative in selected:
        path = source / relative
        expected = contract["files"][relative]
        actual = sha256_file(path)
        rows.append(
            {
                "relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": actual,
                "expected_sha256": expected,
                "matches": actual == expected,
            }
        )
    if not all(row["matches"] for row in rows):
        raise RuntimeError("pinned Source-A file hash mismatch")
    return {"verified_files": rows}


def run_attempt(
    output_dir: Path,
    source_a_run: Path,
    seed: int,
    episode_index: int,
    max_physics_steps: int,
    max_sim_seconds: float,
) -> dict[str, Any]:
    started = time.monotonic()
    branch = source_a_run / "branches" / "A"
    source = branch / "source"
    source_contract_path = branch / "SOURCE_CONTRACT.json"
    source_contract = read_json(source_contract_path)
    verification = verify_source_contract(source, source_contract)
    manifest = {
        "schema": "embodied-s1-native-attempt-manifest/v1",
        "candidate_id": "source_a_g1_manipulation",
        "repository": source_contract["repo"],
        "commit": source_contract["commit"],
        "source_contract": {"path": str(source_contract_path), "sha256": sha256_file(source_contract_path)},
        "seed": seed,
        "episode_index": episode_index,
        "rendering": False,
        "snapshots": False,
        "budgets": {"max_physics_steps": max_physics_steps, "max_sim_seconds": max_sim_seconds},
        **verification,
    }
    write_json_atomic(output_dir / "RUN_MANIFEST.json", manifest)

    sys.path.insert(0, str(source))
    import mujoco
    import numpy as np
    import onnxruntime as ort

    versions = {
        "mujoco": mujoco.__version__,
        "numpy": np.__version__,
        "onnxruntime": ort.__version__,
    }
    expected_versions = source_contract["environment"]
    mismatches = {
        key: {"expected": expected_versions[key], "actual": actual}
        for key, actual in versions.items()
        if expected_versions.get(key) != actual
    }
    preflight = {
        "schema": "embodied-s1-native-preflight/v1",
        "runtime_versions": versions,
        "expected_versions": expected_versions,
        "runtime_contract_matches": not mismatches,
        "mismatches": mismatches,
    }
    write_json_atomic(output_dir / "PREFLIGHT.json", preflight)
    if mismatches:
        raise RuntimeError(f"runtime contract mismatch: {mismatches}")

    from ik import pipeline
    from ik import sim

    spec = importlib.util.spec_from_file_location("source_a_native_sweep", source / "eval/sweep.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the pinned Source-A sweep module")
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    bounds, nominal = sweep.table_bounds(sweep.PRESETS["shipped"].get("cyl_margin_m", 0.045))
    scene = sweep.make_episode(episode_index, seed, "shipped", bounds, nominal)
    kwargs = {
        key: scene[key]
        for key in [
            "spawn",
            "cyl_xy",
            "cyl_mass_scale",
            "cyl_friction",
            "brown_dz",
            "blue_dz",
            "brown_dxy",
            "blue_dxy",
        ]
    }
    kwargs["spawn_yaw"] = scene["spawn_yaw_deg"] * np.pi / 180.0
    write_json_atomic(output_dir / "CASE_DRAW.json", json_safe(scene))
    sim.OUT_DIR = output_dir / "native_output"
    sim.OUT_DIR.mkdir(parents=True, exist_ok=True)
    if pipeline.COMMANDER is not None:
        raise RuntimeError("pinned pipeline already has mutable commander state")

    counters = NativeCounters(mujoco, ort, max_physics_steps, max_sim_seconds)
    result: dict[str, Any] = {}
    error = None
    counters.install()
    try:
        result = pipeline.run_once(
            **kwargs,
            video=None,
            snapshots=False,
            sim_limit=max_sim_seconds,
            wall_limit=850.0,
        )
    except BaseException:
        error = traceback.format_exc()
    finally:
        metrics = counters.close()

    ok = result.get("ok", {}) if isinstance(result, dict) else {}
    native_reproduction_passed = bool(
        result.get("success")
        and ok.get("pick")
        and ok.get("transport")
        and ok.get("place")
        and not error
        and metrics["physics_steps"] > 0
        and metrics["policy_forwards"] > 0
        and metrics["nonfinite_steps"] == 0
        and metrics["external_wrench_violations"] == 0
        and metrics["state_continuity_violations"] == 0
    )
    report = {
        "schema": "embodied-s1-native-attempt-result/v1",
        "candidate_id": "source_a_g1_manipulation",
        "runtime_versions": versions,
        "native_reproduction_passed": native_reproduction_passed,
        "source_result": json_safe(result),
        "audit_metrics": metrics,
        "error": error,
        "wall_seconds": time.monotonic() - started,
        "render_passes": 0,
        "training_updates": 0,
        "manual_interventions": 0,
        "production_accepted": False,
        "learning_validated": False,
        "quality_boundary": "Native task success is S1 evidence only; penetration and data-production gates are not accepted here.",
    }
    write_json_atomic(output_dir / "RESULT.json", report)
    return report


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-a-run", type=Path, default=DEFAULT_SOURCE_A_RUN)
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--episode-index", type=int, default=0)
    parser.add_argument("--max-physics-steps", type=int, default=120000)
    parser.add_argument("--max-sim-seconds", type=float, default=300.0)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    try:
        result = run_attempt(
            args.output_dir,
            args.source_a_run,
            args.seed,
            args.episode_index,
            args.max_physics_steps,
            args.max_sim_seconds,
        )
    except BaseException:
        error = traceback.format_exc()
        write_json_atomic(
            args.output_dir / "RUNNER_FAILURE.json",
            {
                "schema": "embodied-s1-runner-failure/v1",
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
                "physics_steps": result["audit_metrics"]["physics_steps"],
                "policy_forwards": result["audit_metrics"]["policy_forwards"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result["native_reproduction_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
