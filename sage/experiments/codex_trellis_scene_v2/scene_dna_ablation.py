from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

from .architecture import plan_architecture
from .assets import resolve_assets
from .brief import build_baseline_brief
from .io_utils import read_json, write_json
from .scene_graph import build_typed_scene_graph


ABLATION_MODES = (
    "legacy_coarse_tags",
    "user_prompt_only",
    "global_anchor_only",
    "relation_aware",
)


def _acceptance_counts(certificate: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in certificate.get("records", []):
        if not isinstance(item, dict):
            continue
        acceptance = str(item.get("acceptance") or "unknown")
        counts[acceptance] = counts.get(acceptance, 0) + 1
    return dict(sorted(counts.items()))


def run_scene_dna_ablation(
    prompt: str,
    manifest_path: Path | None,
    output_dir: Path,
    *,
    max_new_assets: int = 40,
) -> dict[str, Any]:
    """Run style-source ablations while holding all non-style V2 inputs fixed."""

    output_dir.mkdir(parents=True, exist_ok=True)
    mode_results: list[dict[str, Any]] = []
    invariant_signature: dict[str, Any] | None = None
    for mode in ABLATION_MODES:
        mode_dir = output_dir / mode
        mode_dir.mkdir(parents=True, exist_ok=True)
        brief = build_baseline_brief(prompt)
        architecture = plan_architecture(brief)
        brief["scene_graph"] = build_typed_scene_graph(brief, architecture)
        signature = {
            "object_ids": [str(obj["id"]) for obj in brief["objects"]],
            "requested_dimensions": {
                str(obj["id"]): deepcopy(
                    obj.get("requested_dimensions") or obj.get("dimensions")
                )
                for obj in brief["objects"]
            },
            "architecture": deepcopy(brief.get("architecture")),
            "scene_graph_relation_count": int(
                brief["scene_graph"].get("stats", {}).get("relation_count", 0)
            ),
        }
        if invariant_signature is None:
            invariant_signature = signature
        elif signature != invariant_signature:
            raise RuntimeError("Non-style ablation inputs diverged between modes")
        report = resolve_assets(
            brief,
            mode_dir,
            mode="plan",
            manifest_path=manifest_path,
            trellis_url="http://127.0.0.1:8082",
            seed=20260822,
            timeout=1.0,
            steps=1,
            texture_size=64,
            decimation_target=100,
            pipeline_type="512",
            preprocess_image=False,
            max_new_assets=max_new_assets,
            scene_dna_mode=mode,
        )
        contract = read_json(Path(report["scene_dna_contract"]))
        certificate = read_json(Path(report["harmony_certificate"]))
        mode_results.append(
            {
                "mode": mode,
                "contract_hash": report["scene_dna_contract_hash"],
                "descriptors": deepcopy(
                    contract.get("global_profile", {}).get("descriptors", [])
                ),
                "local_aesthetic_group_count": len(
                    contract.get("local_aesthetic_groups", [])
                ),
                "reused_count": int(report["reused_count"]),
                "missing_instance_count": int(report["missing_count"]),
                "unique_generation_planned_count": int(
                    report["unique_generation_planned_count"]
                ),
                "selected_assets": {
                    str(item["object_id"]): str(item.get("asset_id") or "")
                    for item in report["results"]
                    if item.get("status") == "reused"
                },
                "acceptance_counts": _acceptance_counts(certificate),
                "claims_visual_harmony_pass": bool(
                    certificate["claims_visual_harmony_pass"]
                ),
                "artifacts": {
                    "contract": report["scene_dna_contract"],
                    "generation_plan": report["missing_asset_generation_plan"],
                    "certificate": report["harmony_certificate"],
                },
            }
        )
    summary = {
        "schema": "codex_trellis_scene_dna_ablation_v1",
        "controlled_variables": {
            "same_prompt": True,
            "same_scene_brief_rules": True,
            "same_architecture": True,
            "same_requested_dimensions": True,
            "same_manifest": True,
            "same_generation_budget": True,
            "asset_mode": "plan",
        },
        "manifest": str(manifest_path.resolve()) if manifest_path else None,
        "invariant_signature": invariant_signature,
        "modes": mode_results,
        "limitations": [
            "plan ablation measures retrieval metadata behavior, not rendered visual preference",
            "generated candidates require the later 2D and TRELLIS.2 multi-view evaluation stage",
        ],
    }
    write_json(output_dir / "scene_dna_ablation_summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run controlled SceneDNA asset-selection and generation-plan ablations."
    )
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt")
    prompt_group.add_argument("--prompt-file", type=Path)
    parser.add_argument("--asset-library-manifest", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-new-assets", type=int, default=40)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    prompt = str(args.prompt or "")
    if args.prompt_file:
        prompt = args.prompt_file.read_text(encoding="utf-8")
    run_scene_dna_ablation(
        prompt,
        args.asset_library_manifest,
        args.output_dir,
        max_new_assets=int(args.max_new_assets),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
