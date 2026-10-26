from __future__ import annotations

import argparse
import json
from pathlib import Path

from .asset_index import AssetIndexBuilder
from .content_chain import file_binding


def main() -> None:
    parser = argparse.ArgumentParser(description="Build/update the offline Scene V2 asset index.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = args.manifest.resolve()
    output = (args.output or manifest.with_suffix(".asset_index.sqlite")).resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("manifest assets must be a list")
    with AssetIndexBuilder(output, source_manifest=manifest) as builder:
        ingested = builder.upsert(item for item in assets if isinstance(item, dict))
        metadata = builder.finalize()
    print(json.dumps({"schema": "scene-v2-asset-index-build/v1", "manifest": {"path": str(manifest), **file_binding(manifest)}, "index": {"path": str(output), **file_binding(output)}, "ingested": ingested, "metadata": metadata}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
