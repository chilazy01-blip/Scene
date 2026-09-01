from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .brief import build_asset_generation_spec, render_asset_prompt
from .io_utils import write_json


BENCHMARK_CATEGORIES: dict[str, dict[str, Any]] = {
    "storage_box": {"width": 0.46, "length": 0.34, "height": 0.28},
    "bookcase": {"width": 0.90, "length": 0.32, "height": 1.60},
    "book_stack": {"width": 0.28, "length": 0.20, "height": 0.12},
    "office_chair": {"width": 0.62, "length": 0.62, "height": 1.05},
    "table_lamp": {"width": 0.30, "length": 0.30, "height": 0.52},
    "potted_plant": {"width": 0.42, "length": 0.42, "height": 0.78},
    "slipper": {"width": 0.12, "length": 0.29, "height": 0.09},
}

# Round two keeps the original families for continuity and adds three categories
# whose form profiles already exist in the production contract.  The new
# categories were not used to calibrate the development-only 0.08 form guard.
HELDOUT_ROUND2_CATEGORIES: dict[str, dict[str, Any]] = {
    **BENCHMARK_CATEGORIES,
    "accent_chair": {"width": 0.72, "length": 0.72, "height": 0.88},
    "dining_chair": {"width": 0.48, "length": 0.52, "height": 0.90},
    "floor_lamp": {"width": 0.36, "length": 0.36, "height": 1.62},
}

STYLE_CONDITIONS = (
    {
        "id": "warm_modern",
        "styles": ["warm", "modern", "clean lines"],
        "appearance": "warm beige, natural material, restrained modern detail",
    },
    {
        "id": "cool_industrial",
        "styles": ["cool", "industrial", "clean lines"],
        "appearance": "cool gray, dark metal accents, restrained industrial detail",
    },
)


def build_benchmark_plan(
    output_dir: Path,
    *,
    base_seed: int = 20260823,
    batch_seed_count: int = 3,
    candidate_count: int = 4,
    category_set: str = "original",
) -> dict[str, Any]:
    """Create the sealed-before-generation matrix for a multi-form benchmark."""

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if category_set == "original":
        categories = BENCHMARK_CATEGORIES
    elif category_set == "heldout_round2":
        categories = HELDOUT_ROUND2_CATEGORIES
    else:
        raise ValueError(f"unsupported category set: {category_set}")
    batches: list[dict[str, Any]] = []
    batch_index = 0
    for category, dimensions in categories.items():
        for condition in STYLE_CONDITIONS:
            prompt = (
                f"A {condition['id'].replace('_', ' ')} room requiring one "
                f"{category.replace('_', ' ')} in {condition['appearance']}."
            )
            obj = {
                "id": f"benchmark_{category}_{condition['id']}",
                "category": category,
                "dimensions": deepcopy(dimensions),
                "requested_dimensions": deepcopy(dimensions),
                "provenance": "scene_dna_benchmark",
            }
            spec = build_asset_generation_spec(
                obj, list(condition["styles"]), prompt
            )
            asset_prompt = render_asset_prompt(spec)
            for seed_index in range(batch_seed_count):
                batch_seed = base_seed + batch_index * 100_003 + seed_index * 9_973
                case_payload = {
                    "category": category,
                    "style_condition": condition["id"],
                    "object_prompt": asset_prompt,
                    "semantic_form_contract": deepcopy(
                        spec["semantic_form_contract"]
                    ),
                    "requested_dimensions": deepcopy(dimensions),
                    "batch_seed": batch_seed,
                    "candidate_seeds": [
                        batch_seed + index * 9_973
                        for index in range(candidate_count)
                    ],
                    "candidate_count": candidate_count,
                }
                case_id = "case_" + hashlib.sha256(
                    json.dumps(case_payload, sort_keys=True).encode("utf-8")
                ).hexdigest()[:12]
                batches.append({"case_id": case_id, **case_payload})
            batch_index += 1
    plan = {
        "schema": "scene_dna_multiform_benchmark_plan_v1",
        "frozen_before_generation": True,
        "category_count": len(categories),
        "style_condition_count": len(STYLE_CONDITIONS),
        "batch_seed_count_per_category_style": batch_seed_count,
        "candidate_count_per_batch": candidate_count,
        "batch_count": len(batches),
        "candidate_image_count": len(batches) * candidate_count,
        "categories": list(categories),
        "shape_profiles": sorted(
            {
                str(batch["semantic_form_contract"]["shape_profile"])
                for batch in batches
            }
        ),
        "selection_systems": (
            [
                "hard_eligible_semantic_form_style_current_control",
                "hard_eligible_form_improvement_guard_0.08_treatment",
            ]
            if category_set == "heldout_round2"
            else [
                "legacy_pixel_palette_temperature_detail",
                "semantic_form_style_v1",
            ]
        ),
        "category_set": category_set,
        "heldout_from_form_guard_calibration": category_set == "heldout_round2",
        "form_guard_threshold_frozen_before_generation": (
            0.08 if category_set == "heldout_round2" else None
        ),
        "primary_human_axes": ["semantic", "form"],
        "secondary_human_axes": ["style", "overall"],
        "success_gates": {
            "semantic_form_blind_win_rate_minimum": 0.60,
            "semantic_form_95pct_confidence_lower_bound_above": 0.50,
            "hard_structure_failure_rate_must_not_increase": True,
            "default_pipeline_replacement_before_pass_forbidden": True,
        },
        "batches": batches,
        "limitations": [
            "book_stack is the current project-supported proxy for the requested book family",
            "pilot results determine the later power calculation for at least 100 independent held-out batches",
        ],
    }
    write_json(output_dir / "scene_dna_benchmark_plan.json", plan)
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--base-seed", type=int, default=20260823)
    parser.add_argument("--batch-seed-count", type=int, default=3)
    parser.add_argument("--candidate-count", type=int, default=4)
    parser.add_argument(
        "--category-set",
        choices=("original", "heldout_round2"),
        default="original",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_benchmark_plan(
        args.output_dir,
        base_seed=int(args.base_seed),
        batch_seed_count=int(args.batch_seed_count),
        candidate_count=int(args.candidate_count),
        category_set=str(args.category_set),
    )
    print(json.dumps({key: report[key] for key in ("batch_count", "candidate_image_count", "shape_profiles")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
