"""Freeze the authorized goal, clocks, generation requests and resource limits."""

import argparse
import json
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timezone

from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)

ROOT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/embodied_locomotion_pipeline_20261020_v1"
)
TEMPLATE = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/embodied_generated_scene_smoke_20261015_v4/generator_request"
)


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    start = datetime.now(timezone.utc).timestamp()
    plan = {
        "schema": "locomotion-goal-plan/v1",
        "started_utc_timestamp": start,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "main_goal": "3 generated scenes, target-driven walk/stop, 48 frozen development conditions, >=80% success, audited data and visual delivery",
        "conditional_carry": {
            "if_main_goal_accepted_within_s": 7200,
            "next": "free-object contact-supported standing hold then short carry walk feasibility",
            "fixed_or_welded_object_cannot_count": True,
        },
        "matrix_design": {
            "scenes": 3,
            "goal_distances_m": [0.4, 0.7],
            "start_poses": 2,
            "initialization_seeds": [101, 102, 103, 104],
            "planner_seed": 1234,
            "seed_semantics": "small body-state initialization perturbations, not planner seed sweep",
            "attempts": 48,
            "minimum_successes": 39,
        },
        "budgets": {
            "cpu_threads": 1,
            "max_cpu_affinity": 8,
            "memory_gib": 16,
            "single_run_wall_s": 120,
            "episode_active_s": 10,
            "qualification_ticks": 50,
            "short_smoke_ticks": 100,
            "pilot_condition_limit": 8,
            "pilot_failures_per_protocol": 3,
            "matrix_retries": 0,
            "new_download_bytes": 0,
            "training": False,
        },
        "task_thresholds": {
            "target_radius_m": 0.15,
            "min_forward_m": 0.2,
            "each_foot_min_complete_cycles": 1,
            "hold_s": 1,
            "hold_speed_max_m_s": 0.08,
            "hold_drift_max_m": 0.02,
            "hold_joint_rms_max_rad_s": 0.6,
            "hold_both_feet_contact_min_fraction": 0.9,
            "up_min": 0.97,
            "pelvis_min_m": 0.7,
        },
        "frozen_safety": {
            "candidate_delta_rad": 0.5433987842330933,
            "pelvis_min_m": 0.65,
            "up_min": 0.5,
            "penetration_max_m": 0.01,
            "contact_force_max_n": 600,
            "candidate_clipping": False,
        },
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "held_out_evaluation": False,
        "template": {
            p.name: _file_binding(p) for p in TEMPLATE.iterdir() if p.is_file()
        },
        "production_accepted": False,
    }
    plan["content_sha256_excluding_this_field"] = canonical_sha256(plan)
    write_json_atomic(root / "PLAN.json", plan)
    assets = json.loads((TEMPLATE / "asset_manifest.json").read_text())
    furnishing = json.loads((TEMPLATE / "furnishing.json").read_text())
    specifications = [
        ({}, "north"),
        (
            {
                "desk": (2.8, 1.7),
                "explicit_side_table": (2.0, 1.0),
                "office_chair": (3.8, 3.1),
                "bookcase": (4.15, 2.2),
            },
            "south",
        ),
        (
            {
                "desk": (2.7, 2.1),
                "explicit_side_table": (1.8, 1.0),
                "office_chair": (3.4, 2.8),
                "bookcase": (3.9, 1.4),
            },
            "west",
        ),
    ]
    for number, (positions, wall) in enumerate(specifications):
        destination = root / "scenes" / f"S{number+1:02d}"
        destination.mkdir(parents=True)
        write_json_atomic(destination / "asset_manifest.json", assets)
        overrides = deepcopy(furnishing)
        for name, (x, y) in positions.items():
            overrides["object_overrides"][name]["initial_pose"].update(x=x, y=y)
        write_json_atomic(destination / "furnishing.json", overrides)
        cli = [
            "--prompt",
            "A modern study with exactly one wooden desk, one compact side table, one office chair, one bookcase and one floor lamp. Preserve a clear walking area in the western half of the room. No extra furniture.",
            "--furnishing-config",
            str(destination / "furnishing.json"),
            "--output-dir",
            str(destination / "generator"),
            "--profile",
            "development",
            "--room-type",
            "study",
            "--window-wall",
            wall,
            "--expander",
            "rules",
            "--planner",
            "rules",
            "--no-codex-repair",
            "--repair-iterations",
            "2",
            "--asset-mode",
            "reuse",
            "--asset-library-manifest",
            str(destination / "asset_manifest.json"),
            "--seed",
            str(26102001 + number),
            "--assemble",
            "--no-render-preview",
            "--no-scene-render-acceptance",
            "--no-mujoco-check",
            "--hard-min-scene-objects",
            "5",
            "--target-max-scene-objects",
            "5",
            "--max-auto-inferred-assets",
            "0",
            "--max-new-assets",
            "0",
            "--blender-bin",
            "/data/wsj/tools/blender/blender",
        ]
        write_json_atomic(destination / "CLI.json", cli)
    print(root)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=ROOT)
    prepare(p.parse_args().root)
