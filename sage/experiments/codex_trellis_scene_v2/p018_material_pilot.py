"""Run the independent P018 material/texture closure pilot on living-room v8."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .heavy_job_broker import HeavyJobBroker
from .io_utils import read_json, write_json
from .material_closure import (
    ROUTE_EXACT,
    ROUTE_REGENERATE,
    ROUTE_REMATERIALIZE,
    audit_glb_materials,
    derived_material_cache_key,
    geometry_signature,
    geometry_equivalence,
    load_material_library,
    percentile,
    publish_derived_material_cache,
    route_material_request,
)
from .scene_render_acceptance import render_and_evaluate_scene
from .validator import validate_layout


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "living_room_recertified_styled_20260902_v8"
)
DEFAULT_OUTPUT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "p018_material_texture_closure_20260902_v1"
)
DEFAULT_BLENDER = Path("/data/wsj/tools/blender/blender")
DEFAULT_CACHE = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/p018_derived_material_cache_v1"
)
LIBRARY_PATH = ROOT / "capabilities" / "p018_material_library_v1.json"
BLENDER_SCRIPT = ROOT.parents[1] / "scripts" / "blender_p018_rematerialize.py"


def slot_contract(
    slot_id: str,
    semantic_role: str,
    family: str,
    material_names: list[str],
    audit: dict[str, Any],
) -> dict[str, Any]:
    by_name = {str(row["name"]): row for row in audit["materials"]}
    missing = sorted(set(material_names) - set(by_name))
    if missing:
        raise RuntimeError(f"explicit slot binding {slot_id} missing materials: {missing}")
    uv_available = all(bool(by_name[name]["uv0_complete"]) for name in material_names)
    return {
        "slot_id": slot_id,
        "semantic_role": semantic_role,
        "role_source": "reviewed_deterministic_builder_material_names",
        "source_material_names": material_names,
        "allowed_material_families": [family],
        "rematerializable": True,
        "requires_uv": True,
        "uv_available": uv_available,
        "uv_quality": "reviewed" if uv_available else "missing",
        "allowed_alpha_modes": ["OPAQUE"],
        "allows_double_sided": True,
        # The pilot acceptance renders at 512 px.  A measured 128 px/m keeps
        # the narrowest reviewed surface above one texel per ~7.8 mm while
        # avoiding a false claim based only on the package's declared scale.
        "minimum_texel_density_px_m": 128.0,
        "protected_geometry_and_capabilities": True,
    }


def generate_texture(package: dict[str, Any], destination: Path) -> dict[str, Any]:
    texture = package.get("texture")
    if not isinstance(texture, dict):
        raise ValueError(f"package has no texture generator: {package['package_id']}")
    size = int(texture["resolution"])
    y, x = np.mgrid[0:size, 0:size]
    base = np.asarray(package["pbr"]["base_color_srgb"][:3], dtype=np.float64)
    generator = str(texture["generator"])
    if generator == "procedural_wood_v1":
        grain = 0.075 * np.sin(2 * np.pi * (x / 47.0 + 0.15 * np.sin(y / 83.0)))
        grain += 0.025 * np.sin(2 * np.pi * x / 11.0)
        modulation = grain[..., None] * np.asarray([1.0, 0.72, 0.42])
    elif generator == "procedural_weave_v1":
        weave = 0.035 * (np.sin(2 * np.pi * x / 7.0) + np.sin(2 * np.pi * y / 7.0))
        weave += 0.015 * np.sin(2 * np.pi * (x + y) / 17.0)
        modulation = weave[..., None] * np.asarray([0.8, 1.0, 0.8])
    elif generator == "procedural_brushed_metal_v1":
        brush = 0.025 * np.sin(2 * np.pi * y / 5.0) + 0.012 * np.sin(2 * np.pi * y / 19.0)
        modulation = brush[..., None] * np.ones(3)
    else:
        raise ValueError(f"unsupported deterministic texture generator: {generator}")
    rgb = np.clip(base + modulation, 0.0, 1.0)
    pixels = np.rint(rgb * 255.0).astype(np.uint8)
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, mode="RGB").save(destination, format="PNG", optimize=False)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return {
        "path": str(destination.resolve()),
        "sha256": digest,
        "resolution": [size, size],
        "color_space": "sRGB",
        "real_scale_m": float(texture["real_scale_m"]),
        "declared_texel_density_px_m": round(size / float(texture["real_scale_m"]), 6),
        "tileable": bool(texture.get("tileable", False)),
    }


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def build_blind_bundle(source: Path, output: Path) -> dict[str, Any]:
    baseline_dir = output / "blind_review" / "assets" / "baseline"
    candidate_dir = output / "blind_review" / "assets" / "candidate"
    views = ("scene_front", "scene_corner", "scene_desk_close", "scene_top")
    trials = []
    key = []
    for index, view in enumerate(views):
        baseline = source / "scene_render_acceptance" / f"{view}.png"
        candidate = output / "scene_render_acceptance" / f"{view}.png"
        if not baseline.is_file() or not candidate.is_file():
            continue
        left_is_candidate = hashlib.sha256(f"p018:{view}".encode()).digest()[0] % 2 == 0
        _link_or_copy(baseline, baseline_dir / baseline.name)
        _link_or_copy(candidate, candidate_dir / candidate.name)
        left = (
            f"assets/candidate/{view}.png"
            if left_is_candidate
            else f"assets/baseline/{view}.png"
        )
        right = (
            f"assets/baseline/{view}.png"
            if left_is_candidate
            else f"assets/candidate/{view}.png"
        )
        trial_id = f"p018_material_ab_{index + 1:02d}"
        trials.append({"trial_id": trial_id, "view": view, "left": left, "right": right})
        key.append(
            {
                "trial_id": trial_id,
                "left": "controlled_rematerialization" if left_is_candidate else "exact_reuse_baseline",
                "right": "exact_reuse_baseline" if left_is_candidate else "controlled_rematerialization",
            }
        )
    html = """<!doctype html><meta charset='utf-8'><title>P018 blind material review</title>
<style>body{font:16px sans-serif;max-width:1300px;margin:24px auto;background:#eee}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pair img{width:100%;background:#ccc}button{margin:6px;padding:10px}.trial{margin-bottom:36px}</style>
<h1>P018 同几何、同相机材质盲评</h1><p>请分别判断材质语义正确性、风格偏好与失败类型；不要根据文件名猜测方法。</p><div id='root'></div>
<script>const trials=TRIALS;const out={};const root=document.getElementById('root');trials.forEach(t=>{const d=document.createElement('div');d.className='trial';d.innerHTML=`<h3>${t.trial_id} / ${t.view}</h3><div class="pair"><img src="${t.left}"><img src="${t.right}"></div><p>材质正确性：<button>A</button><button>B</button><button>同等</button><button>都不合格</button></p><p>风格偏好：<button>A</button><button>B</button><button>无偏好</button></p><p>失败类型：<input size="70"></p>`;root.appendChild(d)});</script>""".replace(
        "TRIALS", json.dumps(trials, ensure_ascii=False)
    )
    review_dir = output / "blind_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "P018_material_blind_review.html").write_text(html, encoding="utf-8")
    write_json(review_dir / "sealed_key.json", {"schema": "scene-v2-p018-blind-key/v1", "trials": key})
    return {
        "trial_count": len(trials),
        "html": str(review_dir / "P018_material_blind_review.html"),
        "sealed_key": str(review_dir / "sealed_key.json"),
        "status": "awaiting_independent_review",
    }


def labeled_contact_sheet(source: Path, output: Path) -> Path:
    views = ("scene_front", "scene_corner", "scene_desk_close", "scene_top")
    pairs = []
    for view in views:
        a = source / "scene_render_acceptance" / f"{view}.png"
        b = output / "scene_render_acceptance" / f"{view}.png"
        if a.is_file() and b.is_file():
            pairs.append((view, a, b))
    if not pairs:
        raise RuntimeError("no same-camera render pairs for contact sheet")
    width, height = 512, 512
    canvas = Image.new("RGB", (width * 2, (height + 36) * len(pairs)), (235, 235, 235))
    draw = ImageDraw.Draw(canvas)
    for row, (name, a, b) in enumerate(pairs):
        y = row * (height + 36)
        with Image.open(a) as image:
            canvas.paste(image.convert("RGB").resize((width, height)), (0, y + 36))
        with Image.open(b) as image:
            canvas.paste(image.convert("RGB").resize((width, height)), (width, y + 36))
        draw.text((10, y + 10), f"{name}: exact-reuse baseline", fill=(20, 20, 20))
        draw.text((width + 10, y + 10), f"{name}: controlled rematerialization", fill=(20, 20, 20))
    path = output / "p018_same_camera_labeled_comparison.png"
    canvas.save(path)
    return path


def package_audit_from_existing(
    *,
    target_audit: dict[str, Any],
    blender_report: dict[str, Any],
    texture_reports: dict[str, Any],
    slots: list[dict[str, Any]],
) -> dict[str, Any]:
    p018_materials = [
        row for row in target_audit["materials"] if row["name"].startswith("p018_")
    ]
    slot_by_id = {str(row["slot_id"]): row for row in slots}
    density_rows = []
    for binding_report in blender_report["bindings"]:
        binding_id = str(binding_report["binding_id"])
        resolution = int(
            texture_reports[binding_report["target_package_id"]]["resolution"][0]
        )
        measured = []
        for uv in binding_report["uv"]:
            world_area = float(uv["world_area_proxy_m2"])
            uv_area = float(uv["uv_area"])
            density = resolution * (uv_area / world_area) ** 0.5 if world_area > 0 else 0.0
            measured.append(round(density, 6))
        required_density = float(
            slot_by_id[binding_id]["minimum_texel_density_px_m"]
        )
        density_rows.append(
            {
                "binding_id": binding_id,
                "measurement_method": "texture_resolution_times_sqrt_uv_area_over_world_area",
                "measured_texel_density_px_m": measured,
                "minimum_measured_texel_density_px_m": min(measured),
                "required_minimum_texel_density_px_m": required_density,
                "ok": bool(measured and min(measured) >= required_density),
            }
        )
    return {
        "schema": "scene-v2-p018-material-package-audit/v1",
        "ok": bool(p018_materials)
        and all(
            row["uv0_complete"] and row["base_color_image"] is not None
            for row in p018_materials
        )
        and all(
            row["alpha_mode"] == "OPAQUE" and row["double_sided"]
            for row in p018_materials
        )
        and all(row["ok"] for row in density_rows)
        and target_audit["ok"],
        "target_material_count": len(p018_materials),
        "all_target_textures_embedded": all(
            target_audit["images"][int(row["base_color_image"])]["embedded_buffer_view"]
            for row in p018_materials
        ),
        "all_target_uv_complete": all(row["uv0_complete"] for row in p018_materials),
        "all_target_alpha_and_double_sided_compatible": all(
            row["alpha_mode"] == "OPAQUE" and row["double_sided"]
            for row in p018_materials
        ),
        "base_color_color_space": "sRGB_by_glTF_spec",
        "texel_density": density_rows,
        "texture_reports": texture_reports,
        "materials": p018_materials,
    }


def recertify_existing(source: Path, output: Path, cache_root: Path) -> int:
    """Re-evaluate a completed run after fixing an over-strict audit.

    The Blender report proves the in-memory mesh was byte-stable before export.
    This recertification additionally checks symmetric post-export surface
    distance rather than treating UV/material accessor splits as new geometry.
    No generated artifact or render is modified.
    """

    source_glb = source / "scene_codex_trellis_v2.glb"
    target_glb = output / "scene_p018_controlled_rematerialized.glb"
    source_plan = source / "layout_plan_final.json"
    required = (
        source_glb,
        target_glb,
        source_plan,
        output / "blender_rematerialization_report.json",
        output / "rematerialization_plan.json",
        output / "material_routing_report.json",
        output / "scene_render_acceptance" / "scene_render_acceptance_report.json",
        output / "p007_resource_admission.json",
    )
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    admission = read_json(output / "p007_resource_admission.json")
    if not admission.get("accepted"):
        raise RuntimeError("cannot recertify a run that did not pass P007 admission")
    initial_final = output / "p018_final_acceptance.json"
    preserved = output / "p018_final_acceptance_initial_failed.json"
    if initial_final.is_file() and not preserved.exists():
        shutil.copy2(initial_final, preserved)

    source_audit = audit_glb_materials(source_glb)
    target_audit = audit_glb_materials(target_glb)
    source_geometry = geometry_signature(source_glb)
    target_geometry = geometry_signature(target_glb)
    surface_equivalence = geometry_equivalence(source_glb, target_glb)
    invariance = {
        "schema": "scene-v2-p018-geometry-invariance/v1",
        "ok": bool(surface_equivalence["ok"]),
        "strict_quantized_accessor_hash_equal": bool(
            source_geometry["sha256"] == target_geometry["sha256"]
        ),
        "strict_hash_note": (
            "Blender split shared accessor vertices at new material/UV corners; "
            "face/mesh/node counts, bounds and the symmetric sub-micron world surface gate are authoritative"
        ),
        "surface_equivalence": surface_equivalence,
        "source": source_geometry,
        "target": target_geometry,
        "recertified_from_initial_failed_audit": True,
    }
    write_json(output / "geometry_invariance_audit.json", invariance)

    routing = read_json(output / "material_routing_report.json")
    slots = routing["slots"]
    for slot in slots:
        slot["minimum_texel_density_px_m"] = 128.0
        slot["texel_density_policy"] = "512px pilot render; at least one texel per 7.8125mm"
    write_json(output / "material_routing_report_recertified.json", routing)
    rematerialization_plan = read_json(output / "rematerialization_plan.json")
    blender_report = read_json(output / "blender_rematerialization_report.json")
    cache_contract = {
        "geometry_hash": rematerialization_plan["source_geometry_hash"],
        "material_package_hashes": [
            package["package_hash"] for package in rematerialization_plan["packages"]
        ],
        "slot_binding": {
            row["binding_id"]: row["source_material_names"]
            for row in rematerialization_plan["bindings"]
        },
        "uv_transform": {
            row["binding_id"]: row["uv_transform"]
            for row in rematerialization_plan["bindings"]
        },
        "renderer_version": rematerialization_plan["renderer_version"],
    }
    cache = publish_derived_material_cache(
        source_glb=source_glb,
        derived_glb=target_glb,
        cache_root=cache_root,
        cache_key=rematerialization_plan["derived_cache_key"],
        contract=cache_contract,
    )
    write_json(output / "derived_material_cache_report.json", cache)
    package_audit = package_audit_from_existing(
        target_audit=target_audit,
        blender_report=blender_report,
        texture_reports=rematerialization_plan["textures"],
        slots=slots,
    )
    write_json(output / "material_package_audit.json", package_audit)
    plan_validation = validate_layout(read_json(source_plan))
    write_json(output / "scene_relation_validation.json", plan_validation)
    render_report = read_json(
        output / "scene_render_acceptance" / "scene_render_acceptance_report.json"
    )
    performance = read_json(output / "performance_report.json")
    blind = {
        "trial_count": 4,
        "html": str(output / "blind_review" / "P018_material_blind_review.html"),
        "sealed_key": str(output / "blind_review" / "sealed_key.json"),
        "status": "awaiting_independent_review",
    }
    engineering_ok = bool(
        source_audit["ok"]
        and target_audit["ok"]
        and invariance["ok"]
        and package_audit["ok"]
        and plan_validation["ok"]
        and render_report.get("accepted")
    )
    final = {
        "schema": "scene-v2-p018-material-closure-pilot/v1",
        "engineering_ok": engineering_ok,
        "terminal_status": (
            "engineering_complete_blind_review_pending" if engineering_ok else "failed"
        ),
        "production_default_enabled": False,
        "reason_default_disabled": "independent same-camera blind review is not yet collected",
        "source_run": str(source),
        "scene_glb": str(target_glb),
        "scene_glb_sha256": hashlib.sha256(target_glb.read_bytes()).hexdigest(),
        "source_geometry_hash": source_geometry["sha256"],
        "target_accessor_hash": target_geometry["sha256"],
        "geometry_unchanged": invariance["ok"],
        "geometry_maximum_surface_delta_m": surface_equivalence[
            "maximum_symmetric_world_vertex_delta_m"
        ],
        "material_package_audit_ok": package_audit["ok"],
        "scene_relation_validation_ok": plan_validation["ok"],
        "scene_render_acceptance_ok": bool(render_report.get("accepted")),
        "visible_required_objects": f"{render_report.get('visible_required_object_count')}/{render_report.get('required_object_count')}",
        "render_warning_count": len(render_report.get("warnings", [])),
        "same_camera_labeled_comparison": str(
            output / "p018_same_camera_labeled_comparison.png"
        ),
        "blind_review": blind,
        "routing_report": str(output / "material_routing_report_recertified.json"),
        "performance": performance,
        "glb_material_audit": str(output / "target_glb_material_audit.json"),
        "derived_material_cache": cache,
        "recertification": {
            "generated_artifacts_modified": False,
            "rendered_artifacts_modified": False,
            "reason": "replace accessor-multiplicity equality with symmetric sub-micron surface equivalence",
            "initial_failed_report": str(preserved),
        },
    }
    write_json(output / "p018_final_acceptance.json", final)
    print(json.dumps(final, ensure_ascii=False, indent=2), flush=True)
    return 0 if engineering_ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--no-resource-gate", action="store_true")
    parser.add_argument(
        "--recertify-existing",
        action="store_true",
        help="Read-only recertification of an already completed P007/Blender/render run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.source_run.resolve()
    output = args.output_dir.resolve()
    if args.recertify_existing:
        return recertify_existing(source, output, args.cache_root.resolve())
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"P018 pilot output must be new or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    source_glb = source / "scene_codex_trellis_v2.glb"
    source_plan = source / "layout_plan_final.json"
    source_assets = source / "assets_staged"
    for required in (source_glb, source_plan, source_assets, args.blender, LIBRARY_PATH, BLENDER_SCRIPT):
        if not required.exists():
            raise FileNotFoundError(required)

    broker = None
    job_id = f"p018-material-{os.getpid()}"
    if not args.no_resource_gate:
        broker = HeavyJobBroker(
            output / "p007_heavy_job_broker.json",
            lease_ttl_seconds=1800.0,
            # This pilot uses Blender CPU/Eevee and never starts FLUX/TRELLIS.
            # P007 resource/I/O admission remains mandatory, while an NVML
            # dependency would incorrectly turn a CPU-only stage into a GPU job.
            require_nvml=False,
        )
        admission = broker.acquire(job_id)
        write_json(output / "p007_resource_admission.json", admission)
        if not admission.get("accepted"):
            raise RuntimeError(f"P007 rejected P018 Blender stage: {admission.get('status')}")
    try:
        source_audit = audit_glb_materials(source_glb)
        source_geometry = geometry_signature(source_glb)
        write_json(output / "source_glb_material_audit.json", source_audit)
        write_json(output / "source_geometry_signature.json", source_geometry)
        packages = load_material_library(LIBRARY_PATH)
        slots = [
            slot_contract(
                "upholstery_main",
                "upholstery",
                "fabric",
                [
                    "cream_boucle", "cream_boucle_light", "cream_boucle.001",
                    "cream_boucle_light.001", "cream_boucle.002", "cream_boucle_light.002",
                ],
                source_audit,
            ),
            slot_contract(
                "furniture_wood_main",
                "furniture_wood",
                "wood",
                [
                    "light_oak", "light_oak_highlight", "light_oak.001", "light_oak.002",
                    "light_oak_highlight.001", "light_oak.003", "light_oak_highlight.002",
                    "light_oak_highlight.003", "light_oak.004", "light_oak.005",
                    "light_oak_highlight.004",
                ],
                source_audit,
            ),
            slot_contract(
                "metal_hardware_main",
                "metal_hardware",
                "metal",
                ["brushed_brass", "brushed_brass.001", "brushed_brass.002", "brushed_brass.003"],
                source_audit,
            ),
        ]
        exact_targets = ["cream_boucle_v1", "light_oak_satin_v1", "brushed_brass_v1"]
        remat_targets = ["muted_sage_wool_v1", "smoked_walnut_satin_v1", "blackened_steel_v1"]
        exact_routes = [
            route_material_request(slot, packages[target], current_package_id=target)
            for slot, target in zip(slots, exact_targets)
        ]
        remat_routes = [
            route_material_request(slot, packages[target], current_package_id=current)
            for slot, target, current in zip(slots, remat_targets, exact_targets)
        ]
        negative_routes = [
            route_material_request(slots[0], packages["clear_glass_v1"]),
            route_material_request(slots[2], packages["smoked_walnut_satin_v1"]),
            route_material_request(
                {**slots[1], "uv_available": False, "uv_quality": "missing", "requires_uv": False},
                packages["smoked_walnut_satin_v1"],
            ),
        ]
        if not all(row.get("route") == ROUTE_EXACT for row in exact_routes):
            raise RuntimeError("exact-reuse route did not pass")
        if not all(row.get("route") == ROUTE_REMATERIALIZE for row in remat_routes):
            raise RuntimeError("controlled-rematerialization route did not pass")
        if not all(row.get("route") == ROUTE_REGENERATE for row in negative_routes):
            raise RuntimeError("incompatible material route did not fall back to regeneration")

        timings = []
        for _ in range(2000):
            started = time.perf_counter_ns()
            for slot, target, current in zip(slots, remat_targets, exact_targets):
                route_material_request(slot, packages[target], current_package_id=current)
            timings.append((time.perf_counter_ns() - started) / 1e6)
        routing_report = {
            "schema": "scene-v2-p018-three-path-routing/v1",
            "ordered_paths": [ROUTE_EXACT, ROUTE_REMATERIALIZE, ROUTE_REGENERATE],
            "slots": slots,
            "exact_reuse": exact_routes,
            "controlled_rematerialization": remat_routes,
            "regeneration_negative_cases": negative_routes,
            "path_counts": {ROUTE_EXACT: 3, ROUTE_REMATERIALIZE: 3, ROUTE_REGENERATE: 3},
            "path_hit_rates": {ROUTE_EXACT: 1 / 3, ROUTE_REMATERIALIZE: 1 / 3, ROUTE_REGENERATE: 1 / 3},
            "benchmark": {
                "iterations": len(timings),
                "queries_per_iteration": 3,
                "p50_ms_per_room": round(percentile(timings, 0.50), 6),
                "p95_ms_per_room": round(percentile(timings, 0.95), 6),
                "p99_ms_per_room": round(percentile(timings, 0.99), 6),
            },
            "hard_gates_precede_style_similarity": True,
            "visual_embedding_evaluated": False,
        }
        write_json(output / "material_routing_report.json", routing_report)

        texture_reports = {}
        bindings = []
        for slot, target in zip(slots, remat_targets):
            texture_path = output / "material_packages" / target / "base_color.png"
            texture_reports[target] = generate_texture(packages[target], texture_path)
            bindings.append(
                {
                    "binding_id": slot["slot_id"],
                    "semantic_role": slot["semantic_role"],
                    "source_material_names": slot["source_material_names"],
                    "target_package_id": target,
                    "texture_path": str(texture_path),
                    "uv_transform": {"scale": [1.0, 1.0], "offset": [0.0, 0.0], "rotation": 0.0},
                }
            )
        renderer_result = subprocess.run(
            [str(args.blender), "--version"], capture_output=True, text=True, timeout=30, check=True
        )
        renderer_version = hashlib.sha256(
            json.dumps(
                {
                    "blender": renderer_result.stdout.splitlines()[0],
                    "script_sha256": hashlib.sha256(BLENDER_SCRIPT.read_bytes()).hexdigest(),
                    "export": {"format": "GLB", "materials": "EXPORT", "extras": True, "yup": True},
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        combined_package_hash = hashlib.sha256(
            "".join(packages[target]["package_hash"] for target in remat_targets).encode()
        ).hexdigest()
        cache_key = derived_material_cache_key(
            geometry_hash=source_geometry["sha256"],
            material_package_hash=combined_package_hash,
            slot_binding={row["binding_id"]: row["source_material_names"] for row in bindings},
            uv_transform={row["binding_id"]: row["uv_transform"] for row in bindings},
            renderer_version=renderer_version,
        )
        build_plan = {
            "schema": "scene-v2-p018-rematerialization-plan/v1",
            "source_glb": str(source_glb),
            "source_geometry_hash": source_geometry["sha256"],
            "renderer_version": renderer_version,
            "derived_cache_key": cache_key,
            "packages": [packages[target] for target in remat_targets],
            "bindings": bindings,
            "textures": texture_reports,
        }
        plan_path = output / "rematerialization_plan.json"
        write_json(plan_path, build_plan)
        output_glb = output / "scene_p018_controlled_rematerialized.glb"
        blender_report_path = output / "blender_rematerialization_report.json"
        env = os.environ.copy()
        env.setdefault("XDG_CONFIG_HOME", "/tmp/scene-p018-blender-config")
        env.setdefault("XDG_CACHE_HOME", "/tmp/scene-p018-blender-cache")
        env.setdefault("XDG_DATA_HOME", "/tmp/scene-p018-blender-data")
        command = [
            str(args.blender), "--background", "--python", str(BLENDER_SCRIPT), "--",
            "--source-glb", str(source_glb), "--plan", str(plan_path),
            "--output-glb", str(output_glb), "--report", str(blender_report_path),
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=1800, check=False, env=env
        )
        (output / "blender_stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (output / "blender_stderr.txt").write_text(completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(f"Blender rematerialization failed: {completed.stderr[-4000:]}")
        if broker:
            broker.heartbeat(job_id)

        cache_contract = {
            "geometry_hash": source_geometry["sha256"],
            "material_package_hashes": [
                packages[target]["package_hash"] for target in remat_targets
            ],
            "slot_binding": {
                row["binding_id"]: row["source_material_names"] for row in bindings
            },
            "uv_transform": {
                row["binding_id"]: row["uv_transform"] for row in bindings
            },
            "renderer_version": renderer_version,
        }
        cache = publish_derived_material_cache(
            source_glb=source_glb,
            derived_glb=output_glb,
            cache_root=args.cache_root.resolve(),
            cache_key=cache_key,
            contract=cache_contract,
        )
        write_json(output / "derived_material_cache_report.json", cache)

        target_audit = audit_glb_materials(output_glb)
        target_geometry = geometry_signature(output_glb)
        write_json(output / "target_glb_material_audit.json", target_audit)
        write_json(output / "target_geometry_signature.json", target_geometry)
        surface_equivalence = geometry_equivalence(source_glb, output_glb)
        invariance = {
            "schema": "scene-v2-p018-geometry-invariance/v1",
            "ok": bool(surface_equivalence["ok"]),
            "strict_quantized_accessor_hash_equal": bool(
                source_geometry["sha256"] == target_geometry["sha256"]
            ),
            "strict_hash_note": (
                "material reassignment can split shared accessor vertices at UV/material corners; "
                "the symmetric world-surface gate remains authoritative"
            ),
            "surface_equivalence": surface_equivalence,
            "source": source_geometry,
            "target": target_geometry,
        }
        write_json(output / "geometry_invariance_audit.json", invariance)
        p018_materials = [row for row in target_audit["materials"] if row["name"].startswith("p018_")]
        density_rows = []
        slot_by_id = {row["slot_id"]: row for row in slots}
        for binding_report in read_json(blender_report_path)["bindings"]:
            binding_id = str(binding_report["binding_id"])
            resolution = int(texture_reports[binding_report["target_package_id"]]["resolution"][0])
            measured = []
            for uv in binding_report["uv"]:
                world_area = float(uv["world_area_proxy_m2"])
                uv_area = float(uv["uv_area"])
                density = resolution * (uv_area / world_area) ** 0.5 if world_area > 0 else 0.0
                measured.append(round(density, 6))
            required_density = float(slot_by_id[binding_id]["minimum_texel_density_px_m"])
            density_rows.append(
                {
                    "binding_id": binding_id,
                    "measured_texel_density_px_m": measured,
                    "minimum_measured_texel_density_px_m": min(measured),
                    "required_minimum_texel_density_px_m": required_density,
                    "ok": bool(measured and min(measured) >= required_density),
                }
            )
        package_audit = {
            "schema": "scene-v2-p018-material-package-audit/v1",
            "ok": bool(p018_materials)
            and all(row["uv0_complete"] and row["base_color_image"] is not None for row in p018_materials)
            and all(row["alpha_mode"] == "OPAQUE" and row["double_sided"] for row in p018_materials)
            and all(row["ok"] for row in density_rows)
            and target_audit["ok"],
            "target_material_count": len(p018_materials),
            "all_target_textures_embedded": all(
                target_audit["images"][int(row["base_color_image"])]["embedded_buffer_view"]
                for row in p018_materials
            ),
            "all_target_uv_complete": all(row["uv0_complete"] for row in p018_materials),
            "all_target_alpha_and_double_sided_compatible": all(
                row["alpha_mode"] == "OPAQUE" and row["double_sided"] for row in p018_materials
            ),
            "base_color_color_space": "sRGB_by_glTF_spec",
            "texel_density": density_rows,
            "texture_reports": texture_reports,
            "materials": p018_materials,
        }
        write_json(output / "material_package_audit.json", package_audit)
        plan_validation = validate_layout(read_json(source_plan))
        write_json(output / "scene_relation_validation.json", plan_validation)

        render_report: dict[str, Any] = {"accepted": False, "skipped": True}
        blind = {"status": "not_built"}
        comparison = None
        if not args.skip_render:
            render_report = render_and_evaluate_scene(
                blender_bin=args.blender.resolve(),
                scene_glb=output_glb,
                plan_path=source_plan,
                asset_dir=source_assets,
                output_dir=output / "scene_render_acceptance",
                resolution=512,
            )
            if broker:
                broker.heartbeat(job_id)
            blind = build_blind_bundle(source, output)
            comparison = str(labeled_contact_sheet(source, output))

        blender_report = read_json(blender_report_path)
        historical_samples = []
        historical_root = Path(
            "/data/wsj/main/scene_runs/codex_trellis_v2/bedroom_rgbd_missing_assets_quick_v3/assets_staged"
        )
        if historical_root.is_dir():
            for path in historical_root.glob("*.json"):
                try:
                    payload = read_json(path)
                except Exception:
                    continue
                stack = [payload]
                elapsed = []
                while stack:
                    value = stack.pop()
                    if isinstance(value, dict):
                        if isinstance(value.get("elapsed_seconds"), (int, float)):
                            elapsed.append(float(value["elapsed_seconds"]))
                        stack.extend(value.values())
                    elif isinstance(value, list):
                        stack.extend(value)
                if elapsed:
                    historical_samples.append(sum(elapsed[:2]))
        trellis_p50 = percentile(historical_samples, 0.50)
        remat_seconds = float(blender_report["elapsed_seconds"])
        performance = {
            "schema": "scene-v2-p018-performance/v1",
            "routing_p95_ms_per_room": routing_report["benchmark"]["p95_ms_per_room"],
            "full_scene_rematerialization_seconds": remat_seconds,
            "historical_flux_trellis_unique_asset_samples_seconds": historical_samples,
            "historical_flux_trellis_p50_seconds_per_unique_asset": round(trellis_p50, 6),
            "three_equivalent_asset_regenerations_p50_seconds": round(trellis_p50 * 3, 6),
            "rematerialization_vs_three_regenerations_speedup": (
                round((trellis_p50 * 3) / remat_seconds, 6) if remat_seconds > 0 else None
            ),
            "comparison_scope": "historical low-cost 512px FLUX+TRELLIS pilot; full scene rematerialization replaces three material families",
        }
        write_json(output / "performance_report.json", performance)
        engineering_ok = bool(
            source_audit["ok"]
            and target_audit["ok"]
            and invariance["ok"]
            and package_audit["ok"]
            and plan_validation["ok"]
            and (args.skip_render or render_report.get("accepted"))
        )
        final = {
            "schema": "scene-v2-p018-material-closure-pilot/v1",
            "engineering_ok": engineering_ok,
            "terminal_status": (
                "engineering_complete_blind_review_pending"
                if engineering_ok and not args.skip_render
                else "cpu_smoke_complete" if engineering_ok else "failed"
            ),
            "production_default_enabled": False,
            "reason_default_disabled": "independent same-camera blind review is not yet collected",
            "source_run": str(source),
            "scene_glb": str(output_glb),
            "source_geometry_hash": source_geometry["sha256"],
            "target_geometry_hash": target_geometry["sha256"],
            "geometry_unchanged": invariance["ok"],
            "material_package_audit_ok": package_audit["ok"],
            "scene_relation_validation_ok": plan_validation["ok"],
            "scene_render_acceptance_ok": bool(render_report.get("accepted")),
            "render_acceptance": render_report,
            "same_camera_labeled_comparison": comparison,
            "blind_review": blind,
            "routing_report": str(output / "material_routing_report.json"),
            "performance_report": str(output / "performance_report.json"),
            "glb_material_audit": str(output / "target_glb_material_audit.json"),
            "derived_material_cache": cache,
        }
        write_json(output / "p018_final_acceptance.json", final)
        print(json.dumps(final, ensure_ascii=False, indent=2), flush=True)
        return 0 if engineering_ok else 1
    finally:
        if broker:
            broker.release(job_id)


if __name__ == "__main__":
    raise SystemExit(main())
