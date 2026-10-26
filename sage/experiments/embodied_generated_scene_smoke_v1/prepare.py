"""Freeze one fresh SAGE layout request using our own generated table assets."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .common import RUN_ROOT, WORKSPACE, read_json, sha256, write_json


DESK_MANIFEST = (
    WORKSPACE
    / "scene_runs/codex_trellis_v2/bedroom_composition_detail_20260909_v1/"
    "asset_manifest.json"
)
SIDE_TABLE_MANIFEST = (
    WORKSPACE
    / "scene_runs/codex_trellis_v2/living_room_reconstruction_20260914_v1/"
    "prepared_v4/asset_manifest.json"
)

ASSET_SPECS = (
    {
        "source_manifest": DESK_MANIFEST,
        "source_id": "desk_warm_oak_001",
        "object_id": "desk",
        "category": "desk",
        "dimensions": {"width": 0.8, "length": 0.5, "height": 0.73},
        "initial_pose": {"x": 2.351, "y": 2.0, "yaw": 0.0},
    },
    {
        "source_manifest": SIDE_TABLE_MANIFEST,
        "source_id": "living_20260914_side_table",
        "object_id": "explicit_side_table",
        "category": "side_table",
        "dimensions": {"width": 0.7, "length": 0.5, "height": 0.63},
        "initial_pose": {"x": 1.7, "y": 1.2, "yaw": 0.0},
    },
    {
        "source_manifest": DESK_MANIFEST,
        "source_id": "office_chair_black_mesh_001",
        "object_id": "office_chair",
        "category": "office_chair",
        "dimensions": {"width": 0.62, "length": 0.62, "height": 1.05},
        "initial_pose": {"x": 4.0, "y": 3.0, "yaw": 0.0},
    },
    {
        "source_manifest": DESK_MANIFEST,
        "source_id": "physics_reference_bookcase",
        "object_id": "bookcase",
        "category": "bookcase",
        # Preserve the generated mesh's measured proportions; its older library
        # metadata used a much deeper nominal box and fails the runtime fit audit.
        "dimensions": {
            "width": 0.7651308334351883,
            "length": 0.40883664110654067,
            "height": 1.6,
        },
        "initial_pose": {"x": 4.15, "y": 2.1, "yaw": 90.0},
    },
    {
        "source_manifest": DESK_MANIFEST,
        "source_id": "bedroom_detail_desk_floor_lamp",
        "object_id": "floor_lamp",
        "category": "floor_lamp",
        "dimensions": {
            "width": 0.2857714062030821,
            "length": 0.5681025962174232,
            "height": 1.5,
        },
        "initial_pose": {"x": 4.45, "y": 3.55, "yaw": 0.0},
    },
)


def _asset_record(spec: dict[str, Any]) -> dict[str, Any]:
    document = read_json(spec["source_manifest"])
    source = next(
        row for row in document["assets"] if row.get("asset_id") == spec["source_id"]
    )
    record = deepcopy(source)
    source_dimensions = deepcopy(record["dimensions"])
    source_id = record["asset_id"]
    record["asset_id"] = f"generated_scene_smoke_{source_id}"
    record["category"] = spec["category"]
    record["dimensions"] = deepcopy(spec["dimensions"])
    record["asset_lifecycle_status"] = record.get(
        "asset_lifecycle_status", record.get("lifecycle_status", "curated")
    )
    record["qa_status"] = "approved"
    record["styles"] = sorted(set(record.get("styles", ())) | {"modern", "warm"})
    record["experiment_retargeting"] = {
        "mode": "declared_axis_normalization_for_controller_compatible_task_envelope",
        "source_asset_id": source_id,
        "source_dimensions_m": source_dimensions,
        "target_dimensions_m": spec["dimensions"],
        "geometry_regenerated": False,
        "visual_asset_origin": "our_previously_generated_asset_library",
        "physical_contact_proxy": "built_later_from_final_SAGE_dimensions",
    }
    path = Path(record["glb_path"])
    if not path.is_file():
        raise FileNotFoundError(path)
    record["experiment_source_sha256"] = sha256(path)
    return record


def prepare(run_root: Path) -> dict[str, Any]:
    if run_root.exists():
        raise FileExistsError(f"refusing to overwrite existing run: {run_root}")
    request = run_root / "generator_request"
    request.mkdir(parents=True)
    assets = [_asset_record(spec) for spec in ASSET_SPECS]
    manifest_path = request / "asset_manifest.json"
    write_json(
        manifest_path,
        {
            "schema": "generated-scene-smoke-asset-library/v1",
            "library_id": "own_generated_tables_controller_isolation",
            "assets": assets,
        },
    )
    prompt_path = request / "prompt.txt"
    prompt_path.write_text(
        "A five by four metre modern study containing exactly one warm wooden desk, "
        "one compact side table, one office chair, one open bookcase, and one floor lamp. "
        "Keep a clear walking corridor between and around the two task tables. Reuse only "
        "the specified assets. No extra furnishings.\n",
        encoding="utf-8",
    )
    overrides = {}
    for spec, asset in zip(ASSET_SPECS, assets):
        overrides[spec["object_id"]] = {
            "dimensions": spec["dimensions"],
            "requested_dimensions": spec["dimensions"],
            "initial_pose": spec["initial_pose"],
            "preferred_wall": None,
            "facing_constraint": None,
            "asset_id": asset["asset_id"],
        }
    furnishing_path = request / "furnishing.json"
    write_json(
        furnishing_path,
        {"schema": "scene-furnishing-groups/v1", "object_overrides": overrides},
    )
    generator_output = run_root / "generator"
    cli = [
        "--prompt-file",
        str(prompt_path),
        "--furnishing-config",
        str(furnishing_path),
        "--output-dir",
        str(generator_output),
        "--profile",
        "development",
        "--room-type",
        "study",
        "--window-wall",
        "north",
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
        str(manifest_path),
        "--seed",
        "26101501",
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
    ]
    write_json(request / "CLI.json", cli)
    protocol = {
        "schema": "embodied-generated-scene-smoke-protocol/v1",
        "purpose": "isolate scene/fixture assets from the unchanged Source-A controller",
        "attempt_limit": 1,
        "layout_seed": 26101501,
        "trajectory_case": "reuse exact S3 seed-3 episode-0 spawn and object draw",
        "controlled_variables": [
            "Source-A robot XML and hand collision meshes",
            "four ONNX controller weights",
            "controller code and task sequence",
            "task-object analytic geometry, mass, friction, and initial XY draw",
            "tabletop task envelope dimensions and heights",
        ],
        "changed_variables": [
            "SAGE-generated room/layout",
            "desk and side-table visual assets from our generated asset library",
            "fresh analytic support/leg proxies derived from generated layout dimensions",
        ],
        "production_accepted": False,
        "long_run_authorized": False,
    }
    write_json(run_root / "PROTOCOL.json", protocol)
    report = {
        "prepared": True,
        "run_root": str(run_root),
        "generator_output": str(generator_output),
        "asset_manifest_sha256": sha256(manifest_path),
        "assets": [
            {
                "asset_id": row["asset_id"],
                "glb_path": row["glb_path"],
                "sha256": row["experiment_source_sha256"],
                "target_dimensions_m": row["dimensions"],
            }
            for row in assets
        ],
    }
    write_json(run_root / "PREPARE_RESULT.json", report)
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    args = parser.parse_args(argv)
    print(prepare(args.run_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

