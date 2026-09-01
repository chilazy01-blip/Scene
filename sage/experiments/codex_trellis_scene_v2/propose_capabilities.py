from __future__ import annotations

import argparse
import json
from pathlib import Path

from .capabilities import capability_index, load_capability_registry
from .capability_proposer import propose_geometry_capabilities
from .collision_proxy import load_normalized_asset_mesh
from .multilevel_proxy import load_multilevel_proxy, mesh_content_hash


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Propose review-required geometry capabilities for one asset."
    )
    parser.add_argument("--capability-registry", type=Path, required=True)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--proxy-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-verify-hash", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = load_capability_registry(args.capability_registry)
    assets = capability_index(registry)
    if args.asset_id not in assets:
        raise KeyError(f"unknown capability asset id: {args.asset_id}")
    mesh, _ = load_normalized_asset_mesh(
        assets[args.asset_id],
        args.asset_root,
        verify_hash=not args.no_verify_hash,
    )
    proxy = load_multilevel_proxy(args.proxy_manifest)
    if proxy.manifest.get("mesh_hash") != mesh_content_hash(mesh):
        raise ValueError("proxy is stale for the normalized asset mesh")
    proposal = propose_geometry_capabilities(
        mesh,
        proxy.levels[str(proxy.manifest["finest_level"])],
        asset_id=args.asset_id,
    )
    payload = json.dumps(proposal, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
