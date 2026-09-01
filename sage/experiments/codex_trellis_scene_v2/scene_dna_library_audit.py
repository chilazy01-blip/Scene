from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .io_utils import read_json, write_json


def audit_asset_library(
    manifest: dict[str, Any],
    *,
    required_categories: list[str] | None = None,
    minimum_assets_per_category: int = 3,
    minimum_style_signatures_per_category: int = 2,
) -> dict[str, Any]:
    """Report whether re-ranking has enough real choices to be meaningful.

    Style signatures deliberately use the manifest's explicit style tags.  The
    audit does not infer unrecorded visual properties and never promotes assets.
    """

    assets = manifest.get("assets")
    assets = assets if isinstance(assets, list) else []
    approved = [
        row
        for row in assets
        if isinstance(row, dict) and str(row.get("qa_status", "")).lower() == "approved"
    ]
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in approved:
        category = str(row.get("category") or "").strip()
        if category:
            by_category[category].append(row)

    categories = sorted(set(required_categories or by_category))
    category_reports: dict[str, dict[str, Any]] = {}
    gaps: list[dict[str, Any]] = []
    for category in categories:
        rows = by_category.get(category, [])
        signatures = Counter(
            tuple(sorted(str(tag).strip().lower() for tag in row.get("styles", []) if str(tag).strip()))
            for row in rows
        )
        missing_metadata = {
            field: sum(not bool(row.get(field)) for row in rows)
            for field in ("styles", "dimensions", "asset_canonical_front", "source", "glb_path")
        }
        assets_ok = len(rows) >= int(minimum_assets_per_category)
        styles_ok = len(signatures) >= int(minimum_style_signatures_per_category)
        if not assets_ok:
            gaps.append(
                {
                    "category": category,
                    "type": "insufficient_approved_assets",
                    "current": len(rows),
                    "target": int(minimum_assets_per_category),
                }
            )
        if not styles_ok:
            gaps.append(
                {
                    "category": category,
                    "type": "insufficient_style_signatures",
                    "current": len(signatures),
                    "target": int(minimum_style_signatures_per_category),
                }
            )
        category_reports[category] = {
            "approved_asset_count": len(rows),
            "style_signature_count": len(signatures),
            "style_signatures": [
                {"tags": list(signature), "count": count}
                for signature, count in sorted(signatures.items())
            ],
            "asset_ids": [str(row.get("asset_id")) for row in rows],
            "missing_metadata_counts": missing_metadata,
            "ready_for_choice_reranking": assets_ok and styles_ok,
        }

    return {
        "schema": "scene_dna_asset_library_coverage_audit_v1",
        "library_id": manifest.get("library_id"),
        "approved_asset_count": len(approved),
        "category_count": len(by_category),
        "required_category_count": len(categories),
        "thresholds": {
            "minimum_assets_per_category": int(minimum_assets_per_category),
            "minimum_style_signatures_per_category": int(minimum_style_signatures_per_category),
        },
        "ready_for_choice_reranking": bool(categories) and not gaps,
        "categories": category_reports,
        "gaps": gaps,
        "interpretation": (
            "A category below threshold can still be used, but style-aware ranking cannot be "
            "validated as a choice mechanism until independently QA-approved alternatives exist."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit curated asset diversity for Scene DNA ranking.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--required-category", action="append", default=[])
    parser.add_argument("--minimum-assets", type=int, default=3)
    parser.add_argument("--minimum-style-signatures", type=int, default=2)
    args = parser.parse_args()
    report = audit_asset_library(
        read_json(args.manifest),
        required_categories=args.required_category or None,
        minimum_assets_per_category=args.minimum_assets,
        minimum_style_signatures_per_category=args.minimum_style_signatures,
    )
    write_json(args.output, report)
    print(args.output)


if __name__ == "__main__":
    main()
