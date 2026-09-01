from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .capabilities import capability_index, load_capability_registry
from .collision_proxy import load_normalized_asset_mesh
from .collision_mesh_cleanup import (
    CollisionMeshCleanupConfig,
    cleanup_collision_mesh,
)
from .multilevel_proxy import (
    ProxyLevelSpec,
    compile_multilevel_proxy,
    save_multilevel_proxy,
)


def parse_level_specs(value: str) -> list[ProxyLevelSpec]:
    specs: list[ProxyLevelSpec] = []
    for raw in value.split(","):
        parts = raw.strip().split(":")
        if len(parts) not in {2, 3}:
            raise argparse.ArgumentTypeError(
                "levels must use name:pitch_m[:dilation_voxels]"
            )
        try:
            spec = ProxyLevelSpec(
                name=parts[0],
                pitch_m=float(parts[1]),
                surface_dilation_voxels=int(parts[2]) if len(parts) == 3 else 1,
            )
            spec.validate()
        except (TypeError, ValueError) as error:
            raise argparse.ArgumentTypeError(str(error)) from error
        specs.append(spec)
    return specs


def compile_registry_proxies(
    registry_path: Path,
    asset_root: Path,
    output_directory: Path,
    *,
    specs: list[ProxyLevelSpec],
    asset_ids: list[str] | None = None,
    verify_hash: bool = True,
    maximum_split_components: int = 512,
    cleanup_collision_meshes: bool = False,
    cleanup_config: CollisionMeshCleanupConfig | None = None,
) -> dict[str, Any]:
    registry = load_capability_registry(registry_path)
    by_id = capability_index(registry)
    selected_ids = asset_ids or sorted(by_id)
    unknown = sorted(set(selected_ids) - set(by_id))
    if unknown:
        raise KeyError("unknown capability asset ids: " + ", ".join(unknown))
    reports: list[dict[str, Any]] = []
    for asset_id in selected_ids:
        capability = by_id[asset_id]
        mesh, normalization = load_normalized_asset_mesh(
            capability, asset_root, verify_hash=verify_hash
        )
        cleanup_report = None
        if cleanup_collision_meshes:
            cleaned_mesh, cleanup_report = cleanup_collision_mesh(
                mesh, cleanup_config
            )
            if cleanup_report["accepted"]:
                mesh = cleaned_mesh
        proxy = compile_multilevel_proxy(
            mesh,
            specs,
            padding_voxels=int(capability["collision_proxy"]["padding_voxels"]),
            maximum_split_components=maximum_split_components,
            metadata={
                "asset_id": asset_id,
                "source_sha256": normalization["source_sha256"],
                "normalization": normalization,
            },
        )
        manifest_path = save_multilevel_proxy(proxy, output_directory / asset_id)
        reports.append(
            {
                "asset_id": asset_id,
                "manifest": str(manifest_path),
                "mesh_hash": proxy.manifest["mesh_hash"],
                "build_hash": proxy.manifest["build_hash"],
                "component_count": proxy.levels[proxy.manifest["finest_level"]].metadata[
                    "component_count"
                ],
                "collision_mesh_cleanup": cleanup_report,
                "collision_mesh_source": (
                    "cleaned_collision_copy"
                    if cleanup_report and cleanup_report["accepted"]
                    else "normalized_visual_mesh"
                ),
            }
        )
    return {
        "schema": "codex_trellis_collision_proxy_compile_report_v1",
        "registry": str(registry_path),
        "asset_root": str(asset_root),
        "output_directory": str(output_directory),
        "asset_count": len(reports),
        "assets": reports,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile component-aware multilevel collision proxies."
    )
    parser.add_argument("--capability-registry", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--asset-id", action="append", dest="asset_ids")
    parser.add_argument(
        "--levels",
        type=parse_level_specs,
        default=parse_level_specs("coarse:0.04:1,fine:0.015:1"),
    )
    parser.add_argument("--no-verify-hash", action="store_true")
    parser.add_argument("--maximum-split-components", type=int, default=512)
    parser.add_argument(
        "--cleanup-collision-meshes",
        action="store_true",
        help="Use an audited collision-only cleanup copy; never overwrites the visual GLB.",
    )
    parser.add_argument("--cleanup-maximum-components", type=int, default=512)
    parser.add_argument("--cleanup-minimum-retained-area", type=float, default=0.995)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = compile_registry_proxies(
        args.capability_registry,
        args.asset_root,
        args.output_dir,
        specs=args.levels,
        asset_ids=args.asset_ids,
        verify_hash=not args.no_verify_hash,
        maximum_split_components=args.maximum_split_components,
        cleanup_collision_meshes=bool(args.cleanup_collision_meshes),
        cleanup_config=CollisionMeshCleanupConfig(
            maximum_components=int(args.cleanup_maximum_components),
            minimum_retained_area_fraction=float(
                args.cleanup_minimum_retained_area
            ),
        ),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
