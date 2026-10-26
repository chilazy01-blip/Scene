"""Run and audit a frozen multi-category/multi-seed Flux-to-TRELLIS batch.

This is an experiment runner, not a furniture generator.  Furniture geometry
comes only from the configured Flux/RMBG/TRELLIS bridge; Blender is used after
generation solely to import each GLB and capture diagnostic views.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .asset_source_policy import audit_asset_source_policy
from .scene_dna_multiview import render_and_evaluate_generated_asset


LOW_UNDER_AXES = (
    "low_+x", "low_-x", "low_+y", "low_-y",
    "under_+x", "under_-x", "under_+y", "under_-y",
)


def frozen_cases() -> list[dict[str, Any]]:
    """Return the pre-registered cases; callers must not filter by outcome."""

    common = (
        "single isolated furniture product, complete object fully visible, "
        "three-quarter product view, realistic materials"
    )
    return [
        {
            "id": "sofa_seed_2026090401",
            "category": "sofa",
            "seed": 2026090401,
            "dimensions": {"width": 2.15, "length": 0.92, "height": 0.86},
            "shape_profile": "upholstered_seating",
            "prompt": f"{common}, modern three-seat cream boucle sofa with four clearly separated visible wooden legs",
        },
        {
            "id": "sofa_seed_2026090402",
            "category": "sofa",
            "seed": 2026090402,
            "dimensions": {"width": 2.15, "length": 0.92, "height": 0.86},
            "shape_profile": "upholstered_seating",
            "prompt": f"{common}, contemporary sage fabric three-seat sofa with four clearly separated visible legs",
        },
        {
            "id": "accent_chair_seed_2026090411",
            "category": "accent_chair",
            "seed": 2026090411,
            "dimensions": {"width": 0.78, "length": 0.82, "height": 0.90},
            "shape_profile": "upholstered_seating",
            "prompt": f"{common}, upholstered accent armchair in warm beige fabric with four clearly separated visible legs",
        },
        {
            "id": "accent_chair_seed_2026090412",
            "category": "accent_chair",
            "seed": 2026090412,
            "dimensions": {"width": 0.78, "length": 0.82, "height": 0.90},
            "shape_profile": "upholstered_seating",
            "prompt": f"{common}, rounded blue lounge armchair with four clearly separated visible oak legs",
        },
        {
            "id": "dining_chair_seed_2026090421",
            "category": "dining_chair",
            "seed": 2026090421,
            "dimensions": {"width": 0.50, "length": 0.55, "height": 0.90},
            "shape_profile": "skeletal_support",
            "prompt": f"{common}, light oak dining chair with upholstered seat and four clearly separated slender legs",
        },
        {
            "id": "dining_chair_seed_2026090422",
            "category": "dining_chair",
            "seed": 2026090422,
            "dimensions": {"width": 0.50, "length": 0.55, "height": 0.90},
            "shape_profile": "skeletal_support",
            "prompt": f"{common}, walnut dining side chair with curved back and four clearly separated visible legs",
        },
        {
            "id": "office_chair_seed_2026090431",
            "category": "office_chair",
            "seed": 2026090431,
            "dimensions": {"width": 0.68, "length": 0.68, "height": 1.12},
            "shape_profile": "skeletal_support",
            "prompt": f"{common}, ergonomic wheeled office chair with one central column and five separated caster spokes",
        },
        {
            "id": "office_chair_seed_2026090432",
            "category": "office_chair",
            "seed": 2026090432,
            "dimensions": {"width": 0.68, "length": 0.68, "height": 1.12},
            "shape_profile": "skeletal_support",
            "prompt": f"{common}, black mesh wheeled office chair with central column and five distinct caster spokes",
        },
    ]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _json_request(url: str, payload: dict[str, Any] | None = None, timeout: float = 60.0) -> tuple[int, bytes, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read(), str(response.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(), str(exc.headers.get("Content-Type") or "")


def _submit_and_wait(bridge_url: str, request: dict[str, Any], timeout: float) -> dict[str, Any]:
    status, body, _ = _json_request(bridge_url.rstrip("/") + "/generate", request, timeout=60.0)
    if status != 202:
        raise RuntimeError(f"bridge rejected request ({status}): {body[:1000]!r}")
    accepted = json.loads(body.decode("utf-8"))
    job_id = str(accepted["job_id"])
    deadline = time.time() + float(timeout)
    last_status = None
    while time.time() < deadline:
        status, body, content_type = _json_request(
            bridge_url.rstrip("/") + f"/job/{job_id}", timeout=90.0
        )
        last_status = status
        if status == 200:
            meta_status, meta_body, _ = _json_request(
                bridge_url.rstrip("/") + f"/job/{job_id}/metadata", timeout=60.0
            )
            metadata = json.loads(meta_body.decode("utf-8")) if meta_status == 200 else None
            return {
                "ok": True,
                "job_id": job_id,
                "content_type": content_type,
                "body": body,
                "bridge_metadata": metadata,
            }
        if status == 500:
            meta_status, meta_body, _ = _json_request(
                bridge_url.rstrip("/") + f"/job/{job_id}/metadata", timeout=60.0
            )
            metadata = json.loads(meta_body.decode("utf-8")) if meta_status == 200 else None
            return {
                "ok": False,
                "job_id": job_id,
                "http_status": status,
                "error": body.decode("utf-8", errors="replace"),
                "bridge_metadata": metadata,
            }
        if status not in {202, 404, 410}:
            raise RuntimeError(f"unexpected bridge status {status}: {body[:1000]!r}")
        time.sleep(4.0)
    raise TimeoutError(f"bridge job {job_id} timed out after {timeout}s; last status={last_status}")


def _contract(case: dict[str, Any]) -> dict[str, Any]:
    identifier = str(case["id"])
    return {
        "contract_hash": hashlib.sha256(
            json.dumps(case, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "selection_policy": {"minimum_harmony_score": 0.0},
        "object_profiles": {
            identifier: {
                "semantic_form_contract": {
                    "shape_profile": str(case["shape_profile"]),
                    "maximum_axis_scale_anisotropy": 2.0 if case["category"] in {"sofa", "accent_chair"} else 2.25,
                }
            }
        },
    }


def _object(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(case["id"]),
        "category": str(case["category"]),
        "dimensions": deepcopy(case["dimensions"]),
        "requested_dimensions": deepcopy(case["dimensions"]),
        "asset_prompt": str(case["prompt"]),
        "asset_axis_to_z": 2,
        "asset_axis_to_z_sign": 1.0,
        "asset_local_yaw_offset_degrees": 0.0,
    }


def _alpha_metrics(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    mask = rgba[:, :, 3] >= 24
    rows, cols = np.nonzero(mask)
    if not len(rows):
        return {"ok": False, "reason": "empty_alpha"}
    y0, y1 = int(rows.min()), int(rows.max())
    x0, x1 = int(cols.min()), int(cols.max())
    crop = mask[y0 : y1 + 1, x0 : x1 + 1]
    widths = crop.sum(axis=1).astype(np.float64) / float(max(1, crop.shape[1]))
    lower = widths[int(0.70 * len(widths)) :]
    return {
        "ok": True,
        "foreground_pixels": int(mask.sum()),
        "bbox_xyxy": [x0, y0, x1, y1],
        "bbox_fill_ratio": round(float(crop.mean()), 6),
        "lower_full_width_row_fraction": round(float(np.mean(lower >= 0.92)), 6) if len(lower) else 0.0,
        "lower_maximum_row_occupancy": round(float(lower.max()), 6) if len(lower) else 0.0,
    }


def _contact_sheet(view_paths: dict[str, str], output: Path) -> None:
    size, label = 280, 28
    canvas = Image.new("RGB", (size * 4, (size + label) * 2), "white")
    draw = ImageDraw.Draw(canvas)
    for index, axis in enumerate(LOW_UNDER_AXES):
        row, col = divmod(index, 4)
        path = Path(str(view_paths.get(axis) or ""))
        if path.is_file():
            with Image.open(path) as source:
                rgba = source.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (235, 235, 235, 255))
                background.alpha_composite(rgba)
                thumb = background.convert("RGB")
                thumb.thumbnail((size - 12, size - 12), Image.Resampling.LANCZOS)
                canvas.paste(thumb, (col * size + (size - thumb.width) // 2, row * (size + label) + 6))
        draw.text((col * size + 7, row * (size + label) + size + 5), axis, fill=(20, 20, 20))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def render_low_under(*, blender: Path, script: Path, asset_dir: Path, output_dir: Path, case: dict[str, Any], resolution: int) -> dict[str, Any]:
    import subprocess

    obj = _object(case)
    plan_path = output_dir / "low_under_plan.json"
    write_json(plan_path, {"schema": "low_under_render_plan_v1", "objects": [obj]})
    command = [
        str(blender), "--background", "--python", str(script), "--",
        "--plan", str(plan_path), "--asset-dir", str(asset_dir),
        "--output-dir", str(output_dir), "--object-ids", str(case["id"]),
        "--resolution", str(int(resolution)), "--transparent",
        "--fit-requested-dimensions", "--view-profile", "low_under",
    ]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900, check=False)
    (output_dir / "blender_stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (output_dir / "blender_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        return {"ok": False, "returncode": completed.returncode, "error": completed.stderr[-3000:]}
    manifest_path = output_dir / "asset_turntable_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = manifest.get("views", {}).get(str(case["id"]), {})
    metrics = {axis: _alpha_metrics(Path(str(paths.get(axis) or ""))) for axis in LOW_UNDER_AXES}
    contact = output_dir / "low_under_contact_sheet.png"
    _contact_sheet(paths, contact)
    report = {
        "schema": "furniture_low_under_multiview_audit_v1",
        "ok": len(paths) == len(LOW_UNDER_AXES) and all(item.get("ok") for item in metrics.values()),
        "camera_count": len(paths),
        "axes": list(LOW_UNDER_AXES),
        "views": paths,
        "silhouette_diagnostics": metrics,
        "contact_sheet": str(contact),
        "interpretation": "diagnostic evidence; hard connected-platform decision is made by source isolation and normalized 3D four-view gates",
    }
    write_json(output_dir / "low_under_multiview_report.json", report)
    return report


def _inspect_glb(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "magic": path.read_bytes()[:4].decode("ascii", errors="replace"),
    }
    try:
        import trimesh

        loaded = trimesh.load(path, force="scene")
        geometries = list(loaded.geometry.values())
        report.update(
            {
                "trimesh_loaded": True,
                "geometry_count": len(geometries),
                "vertex_count": int(sum(len(mesh.vertices) for mesh in geometries)),
                "face_count": int(sum(len(mesh.faces) for mesh in geometries)),
                "finite_bounds": bool(np.isfinite(np.asarray(loaded.bounds)).all()),
            }
        )
    except Exception as exc:
        report.update({"trimesh_loaded": False, "error": f"{type(exc).__name__}: {exc}"})
    report["ok"] = bool(report["magic"] == "glTF" and report.get("trimesh_loaded") and report.get("geometry_count", 0) > 0 and report.get("finite_bounds"))
    return report


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = frozen_cases()
    plan = {
        "schema": "white_background_multicategory_multiseed_plan_v1",
        "created_before_generation": True,
        "selection_policy": "all preregistered cases retained regardless of outcome",
        "category_count": len({case["category"] for case in cases}),
        "seed_count": len(cases),
        "cases": cases,
    }
    plan["plan_hash"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8")).hexdigest()
    plan_path = output / "frozen_batch_plan.json"
    if plan_path.is_file() and json.loads(plan_path.read_text(encoding="utf-8")) != plan:
        raise RuntimeError(f"existing frozen plan differs: {plan_path}")
    write_json(plan_path, plan)

    renderer = Path(__file__).resolve().parents[2] / "scripts" / "blender_render_asset_turntables.py"
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        case_dir = output / "cases" / str(case["id"])
        terminal = case_dir / "terminal_result.json"
        if args.resume and terminal.is_file():
            rows.append(json.loads(terminal.read_text(encoding="utf-8")))
            print(f"[{index}/{len(cases)}] resume {case['id']}", flush=True)
            continue
        case_dir.mkdir(parents=True, exist_ok=True)
        request = {
            "image_provider": "flux1-schnell",
            "input_text": str(case["prompt"]),
            "seed": int(case["seed"]),
            "pipeline_type": "512",
            "preprocess_image": True,
            "sparse_steps": int(args.steps),
            "shape_steps": int(args.steps),
            "tex_steps": int(args.steps),
            "texture_size": int(args.texture_size),
            "decimation_target": int(args.decimation_target),
            "simplify_limit": 1_048_576,
            "glb_webp": False,
        }
        write_json(case_dir / "request.json", request)
        print(f"[{index}/{len(cases)}] submit {case['id']}", flush=True)
        try:
            result = _submit_and_wait(args.bridge_url, request, float(args.timeout))
            bridge_meta = result.get("bridge_metadata")
            if bridge_meta is not None:
                write_json(case_dir / "bridge_metadata.json", bridge_meta)
            if not result["ok"]:
                row = {
                    "case_id": case["id"], "category": case["category"], "seed": case["seed"],
                    "status": "source_or_generation_rejected", "job_id": result["job_id"],
                    "error": result.get("error"), "bridge_metadata": str(case_dir / "bridge_metadata.json") if bridge_meta else None,
                }
                write_json(terminal, row)
                rows.append(row)
                continue
            glb_dir = case_dir / "assets"
            glb_dir.mkdir(parents=True, exist_ok=True)
            glb_path = glb_dir / f"{case['id']}.glb"
            glb_path.write_bytes(result["body"])
            generation = {
                "job_id": result["job_id"], "request": request,
                "content_type": result.get("content_type"), "bridge_metadata": bridge_meta,
            }
            write_json(case_dir / "generation.json", generation)
            source = audit_asset_source_policy(
                {"mode": "generate", "results": [{
                    "object_id": case["id"], "category": case["category"],
                    "status": "generated", "metadata": generation,
                }]}
            )
            write_json(case_dir / "source_policy_report.json", source)
            glb = _inspect_glb(glb_path)
            write_json(case_dir / "glb_inspection.json", glb)
            standard = render_and_evaluate_generated_asset(
                blender_bin=args.blender.resolve(), asset_dir=glb_dir,
                output_dir=case_dir / "standard_multiview", obj=_object(case),
                contract=_contract(case), reference_image_path=None,
                resolution=int(args.resolution), geometry_evidence=True,
            )
            low_under = render_low_under(
                blender=args.blender.resolve(), script=renderer, asset_dir=glb_dir,
                output_dir=case_dir / "low_under_multiview", case=case,
                resolution=int(args.resolution),
            )
            connected_platform = not bool(standard.get("structure_gate", {}).get("lower_platform_passed", False))
            accepted = bool(source.get("ok") and glb.get("ok") and standard.get("hard_geometry_gate_passed") and low_under.get("ok"))
            row = {
                "case_id": case["id"], "category": case["category"], "seed": case["seed"],
                "status": "accepted" if accepted else "generated_but_rejected",
                "job_id": result["job_id"], "glb_path": str(glb_path),
                "source_policy_ok": bool(source.get("ok")), "glb_ok": bool(glb.get("ok")),
                "standard_multiview_ok": bool(standard.get("hard_geometry_gate_passed")),
                "low_under_capture_ok": bool(low_under.get("ok")),
                "connected_platform_detected": connected_platform,
                "standard_contact_sheet": standard.get("contact_sheet_path"),
                "low_under_contact_sheet": low_under.get("contact_sheet"),
            }
        except Exception as exc:
            row = {
                "case_id": case["id"], "category": case["category"], "seed": case["seed"],
                "status": "runner_failed", "error": f"{type(exc).__name__}: {exc}",
            }
        write_json(terminal, row)
        rows.append(row)
        write_json(output / "batch_progress.json", {"plan_hash": plan["plan_hash"], "results": rows})

    summary = {
        "schema": "white_background_multicategory_multiseed_result_v1",
        "plan_hash": plan["plan_hash"],
        "requested_case_count": len(cases),
        "terminal_case_count": len(rows),
        "pipeline_completed": len(rows) == len(cases),
        "generated_glb_count": sum(bool(row.get("glb_path")) for row in rows),
        "accepted_glb_count": sum(row.get("status") == "accepted" for row in rows),
        "generated_but_rejected_count": sum(row.get("status") == "generated_but_rejected" for row in rows),
        "source_or_generation_rejected_count": sum(row.get("status") == "source_or_generation_rejected" for row in rows),
        "runner_failed_count": sum(row.get("status") == "runner_failed" for row in rows),
        "connected_platform_detected_count": sum(bool(row.get("connected_platform_detected")) for row in rows),
        "results": rows,
    }
    write_json(output / "validation_summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8082")
    parser.add_argument("--blender", type=Path, default=Path("/data/wsj/tools/blender-4.3.2-linux-x64/blender"))
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--texture-size", type=int, default=512)
    parser.add_argument("--decimation-target", type=int, default=300_000)
    parser.add_argument("--resolution", type=int, default=420)
    parser.add_argument("--timeout", type=float, default=2400.0)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    summary = run(build_parser().parse_args(argv))
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary["pipeline_completed"] and summary["runner_failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
