from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from .io_utils import read_json, write_json
from .showcase_render import (
    RENDER_PROFILES,
    evaluate_showcase_quality,
    select_camera_pair,
    write_profile_contract,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_blender(command: list[str], log_prefix: Path) -> None:
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3600,
        check=False,
    )
    log_prefix.with_suffix(".stdout.txt").write_text(
        completed.stdout, encoding="utf-8"
    )
    log_prefix.with_suffix(".stderr.txt").write_text(
        completed.stderr, encoding="utf-8"
    )
    if completed.returncode or "Traceback (most recent call last)" in completed.stderr:
        raise RuntimeError(
            f"Blender phase failed ({completed.returncode}): {completed.stderr[-4000:]}"
        )


def relation_pairs(plan: dict) -> list[tuple[str, str]]:
    object_ids = {
        str(row["id"])
        for row in plan.get("objects", [])
        if isinstance(row, dict) and row.get("id")
    }
    pairs = []
    for row in plan.get("relations", []):
        if not isinstance(row, dict) or str(row.get("strength") or "soft") != "hard":
            continue
        source, target = str(row.get("source") or ""), str(row.get("target") or "")
        if source in object_ids and target in object_ids and (source, target) not in pairs:
            pairs.append((source, target))
    return pairs


def write_quality_audit(output_dir: Path, scene_glb: Path) -> dict:
    manifest_path = output_dir / "showcase_render_manifest.json"
    manifest = read_json(manifest_path)
    quality = evaluate_showcase_quality(manifest)
    quality["source_glb"] = str(scene_glb.resolve())
    quality["source_glb_sha256"] = sha256(scene_glb)
    quality["render_manifest_sha256"] = sha256(manifest_path)
    for row in quality.get("views", []):
        path = Path(row["path"])
        row["sha256"] = sha256(path)
        selected = next(
            item for item in manifest["selected_views"] if item["id"] == row["id"]
        )
        mask_path = Path(selected["object_index_mask_path"])
        row["object_index_mask_sha256"] = sha256(mask_path)
    quality["relationship_evidence"] = [
        {
            "id": row["id"],
            "path": row["rgb_path"],
            "sha256": sha256(Path(row["rgb_path"])),
        }
        for row in manifest.get("relationship_evidence", [])
    ]
    manual_review_path = output_dir / "showcase_manual_review.json"
    if manual_review_path.is_file():
        quality["manual_review"] = {
            "path": str(manual_review_path.resolve()),
            "sha256": sha256(manual_review_path),
        }
    report_path = output_dir / "showcase_quality_audit.json"
    write_json(report_path, quality)
    return {
        "ok": quality["ok"],
        "quality_report": str(report_path),
        "quality_report_sha256": sha256(report_path),
        "selected_candidate_ids": quality["camera_selection"][
            "selected_candidate_ids"
        ],
        "pair_objective": quality["camera_selection"]["pair_objective"],
        "profiles": RENDER_PROFILES,
    }


def run(args: argparse.Namespace) -> dict:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    profiles_path = args.output_dir / "render_profiles.json"
    write_profile_contract(profiles_path)
    script = Path(__file__).with_name("blender_render_showcase.py")
    base = [
        str(args.blender),
        "--background",
        "--python",
        str(script),
        "--",
        "--scene-glb",
        str(args.scene_glb),
        "--plan",
        str(args.plan),
        "--profiles",
        str(profiles_path),
        "--output-dir",
        str(args.output_dir),
    ]
    run_blender(base + ["--phase", "candidates"], args.output_dir / "candidate_phase")
    candidate_manifest = read_json(args.output_dir / "camera_candidates.json")
    plan = read_json(args.plan)
    required = {
        str(row["id"])
        for row in plan.get("objects", [])
        if isinstance(row, dict) and row.get("id") and bool(row.get("required", True))
    }
    pairs = relation_pairs(plan)
    selection = select_camera_pair(
        candidate_manifest["candidates"],
        required_object_ids=required,
        relation_pairs=pairs,
    )
    selection.update(
        {
            "schema": "codex_trellis_showcase_camera_selection_v1",
            "required_object_ids": sorted(required),
            "relation_pairs": [list(pair) for pair in pairs],
        }
    )
    selection_path = args.output_dir / "camera_selection.json"
    write_json(selection_path, selection)
    run_blender(
        base + ["--phase", "final", "--selection", str(selection_path)],
        args.output_dir / "final_phase",
    )
    return write_quality_audit(args.output_dir, args.scene_glb)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--blender", type=Path, required=True)
    result.add_argument("--scene-glb", type=Path, required=True)
    result.add_argument("--plan", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--audit-only", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    result = (
        write_quality_audit(args.output_dir, args.scene_glb)
        if args.audit_only
        else run(args)
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
