from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import mimetypes
import random
import re
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PIL import Image

from .io_utils import read_json, write_json
from .alpha_hygiene import (
    DEFAULT_REVIEW_BACKGROUND_RGB,
    audit_sanitized_alpha_edges,
    clean_chromatic_alpha_edges,
    composite_on_review_background,
)


AXES = ("semantic", "form", "style", "overall")
CHOICES = {"left", "right", "tie", "neither"}


_OBJECT_REQUIREMENTS_ZH = {
    "storage_box": "一个完整的封闭式长方形布面收纳箱，边缘规整，箱盖清晰可见",
    "bookcase": "一个独立的开放式书柜，两侧有竖直支撑，并有多层重复的水平层板和清晰可见的开放储物格",
    "book_stack": "一摞紧凑摆放的书，包含多本合上的书，封面与书页块层次清晰",
    "office_chair": "一把完整的办公椅，座面、靠背、中央支撑以及稳定的脚轮或椅脚清晰可见",
    "table_lamp": "一盏完整的台灯，灯罩、中央灯杆或灯体以及稳定的一体式灯座清晰可见",
    "potted_plant": "一盆完整的室内盆栽，真实花盆、植物茎干和自然分枝的叶片清晰可见",
    "slipper": "一只完整的开背滑套式室内拖鞋，鞋底、宽鞋面、开放后跟和左脚或右脚形态清晰可见（按单只鞋评价，不要求成双）",
    "accent_chair": "一把完整的休闲椅，座面、靠背、扶手或侧向支撑以及稳定分离的椅腿清晰可见",
    "dining_chair": "一把完整的餐椅，座面、直立靠背以及稳定分离的椅腿清晰可见",
    "floor_lamp": "一盏完整的落地灯，灯罩或灯头、细长灯杆以及一体式稳定底座清晰可见",
}

_STYLE_REQUIREMENTS_ZH = {
    "warm_modern": "温暖现代风格；简洁线条；米色；具有适度真实的材质细节和干净的几何形态",
    "cool_industrial": "冷色工业风格；简洁线条；灰色哑光金属质感；具有适度真实的材质细节和干净的几何形态",
}


def _localized_requirements(
    category: str, object_requirement: str, style_requirement: str
) -> tuple[str, str]:
    """Return stable Chinese display copy without changing evaluation fields."""

    object_zh = _OBJECT_REQUIREMENTS_ZH.get(
        category, f"请根据以下要求判断物体：{object_requirement}"
    )
    ratio_match = re.search(
        r"visual width:length:height proportions about\s+([^\.]+(?:\.[^\.]+){0,3})\.",
        object_requirement,
        flags=re.IGNORECASE,
    )
    if ratio_match:
        object_zh += f"；参考宽:深:高比例约为 {ratio_match.group(1)}"
    object_zh += "；物体应完整、居中，以三分之四视角展示，背景简洁且光照均匀，不应出现房间、周边家具、额外道具、文字、展示台或地面"
    normalized_style = style_requirement.strip().lower().replace(" ", "_")
    style_zh = _STYLE_REQUIREMENTS_ZH.get(
        normalized_style, f"风格代号：{style_requirement}"
    )
    return object_zh, style_zh


def _anonymous_id(value: str, salt: str) -> str:
    return "asset_" + hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:12]


def _prepare_review_image(
    source: Path,
    destination: Path,
    *,
    background_rgb_hint: list[float] | tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """Normalize transparent cutouts before they enter a human questionnaire."""

    image = Image.open(source)
    had_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
    rgba = image.convert("RGBA")
    if background_rgb_hint is None:
        cleaned, hygiene = clean_chromatic_alpha_edges(rgba)
        hygiene_mode = "fallback_inference_and_cleanup"
    else:
        cleaned = rgba
        hygiene = audit_sanitized_alpha_edges(cleaned, background_rgb_hint)
        hygiene_mode = "recorded_background_non_mutating_audit"
    if not bool(hygiene.get("ok", True)):
        raise ValueError(
            f"review image failed chroma-spill QA: {source}: "
            f"{hygiene.get('reasons', [])}"
        )
    standardized = composite_on_review_background(
        cleaned, background_rgb=DEFAULT_REVIEW_BACKGROUND_RGB
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    standardized.save(destination, format="PNG")
    return {
        "schema": "scene_dna_review_image_qa_v1",
        "source_had_alpha": had_alpha,
        "output_mode": "RGB",
        "output_background_rgb": list(DEFAULT_REVIEW_BACKGROUND_RGB),
        "alpha_renderer_independent": True,
        "hygiene_mode": hygiene_mode,
        "chroma_spill_hygiene": hygiene,
    }


def prepare_blind_bundle(
    comparisons_path: Path,
    output_dir: Path,
    *,
    sealed_key_path: Path,
    random_seed: int = 20260823,
    duplicate_fraction: float = 0.10,
) -> dict[str, Any]:
    """Randomize A/B sides and keep method identity outside the public bundle.

    A small hidden repeat set measures reviewer consistency. Repeats are clustered
    with their original case during analysis and therefore never inflate n.
    """

    comparisons = read_json(comparisons_path)
    rows = comparisons.get("comparisons", [])
    output_dir = output_dir.resolve()
    image_dir = output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(random_seed)
    public_trials: list[dict[str, Any]] = []
    key_trials: list[dict[str, Any]] = []
    eligible_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("baseline"), dict)
        and isinstance(row.get("proposed"), dict)
    ]
    trial_specs: list[tuple[dict[str, Any], int, str | None]] = [
        (row, index, None) for index, row in enumerate(eligible_rows)
    ]
    duplicate_count = min(
        len(eligible_rows),
        int(math.ceil(len(eligible_rows) * max(0.0, float(duplicate_fraction)))),
    )
    duplicate_indices = rng.sample(range(len(eligible_rows)), duplicate_count)
    original_trial_ids = {
        index: "trial_"
        + hashlib.sha256(
            f"{random_seed}:{row.get('case_id')}:{index}:original".encode()
        ).hexdigest()[:12]
        for index, row in enumerate(eligible_rows)
    }
    trial_specs.extend(
        (eligible_rows[index], index, original_trial_ids[index])
        for index in duplicate_indices
    )
    original_occurrences = list(range(len(eligible_rows)))
    repeat_occurrences = list(range(len(eligible_rows), len(trial_specs)))

    def balanced_left_occurrences(occurrences: list[int]) -> set[int]:
        """Randomize sides while preventing accidental position imbalance."""

        shuffled = list(occurrences)
        rng.shuffle(shuffled)
        return set(shuffled[: len(shuffled) // 2])

    proposed_left_occurrences = balanced_left_occurrences(
        original_occurrences
    ) | balanced_left_occurrences(repeat_occurrences)
    for occurrence, (row, index, duplicate_of_trial_id) in enumerate(trial_specs):
        if not isinstance(row, dict):
            continue
        baseline = row.get("baseline")
        proposed = row.get("proposed")
        if not isinstance(baseline, dict) or not isinstance(proposed, dict):
            continue
        sides = (
            [("proposed", proposed), ("baseline", baseline)]
            if occurrence in proposed_left_occurrences
            else [("baseline", baseline), ("proposed", proposed)]
        )
        trial_id = (
            original_trial_ids[index]
            if duplicate_of_trial_id is None
            else "trial_"
            + hashlib.sha256(
                f"{random_seed}:{row.get('case_id')}:{index}:repeat:{occurrence}".encode()
            ).hexdigest()[:12]
        )
        public_assets: dict[str, Any] = {}
        sealed_assets: dict[str, Any] = {}
        for side, (method, asset) in zip(("left", "right"), sides):
            source = Path(str(asset["image_path"]))
            anonymous = _anonymous_id(
                str(asset.get("asset_id") or source), f"{random_seed}:{trial_id}:{side}"
            )
            destination = image_dir / f"{anonymous}.png"
            background_rgb_hint = asset.get("alpha_hygiene_background_rgb")
            if not isinstance(background_rgb_hint, (list, tuple)) or len(
                background_rgb_hint
            ) != 3:
                background_rgb_hint = None
            review_image_qa = _prepare_review_image(
                source,
                destination,
                background_rgb_hint=background_rgb_hint,
            )
            public_assets[side] = {
                "anonymous_id": anonymous,
                "image_path": str(destination.relative_to(output_dir)),
            }
            sealed_assets[side] = {
                "method": method,
                "source_asset_id": asset.get("asset_id"),
                "source_image_path": str(source),
                "review_image_qa": review_image_qa,
            }
        object_requirement = str(row.get("object_requirement") or "")
        style_requirement = str(row.get("style_requirement") or "")
        object_zh, style_zh = _localized_requirements(
            str(row.get("category") or ""), object_requirement, style_requirement
        )
        public_trials.append(
            {
                "trial_id": trial_id,
                "case_id": str(row.get("case_id") or ""),
                "category": str(row.get("category") or ""),
                "shape_profile": str(row.get("shape_profile") or ""),
                "object_requirement": object_requirement,
                "style_requirement": style_requirement,
                "object_requirement_zh": object_zh,
                "style_requirement_zh": style_zh,
                "assets": public_assets,
            }
        )
        key_trials.append(
            {
                "trial_id": trial_id,
                "case_id": str(row.get("case_id") or ""),
                "independent_case_id": str(row.get("case_id") or trial_id),
                "duplicate_of_trial_id": duplicate_of_trial_id,
                "assets": sealed_assets,
            }
        )
    paired_trials = list(zip(public_trials, key_trials))
    minimum_repeat_distance = min(
        max(1, len(paired_trials) - 1),
        max(3, len(paired_trials) // 5),
    )
    for _ in range(1000):
        rng.shuffle(paired_trials)
        positions = {
            key_item["trial_id"]: position
            for position, (_, key_item) in enumerate(paired_trials)
        }
        repeat_distances = [
            abs(
                positions[key_item["trial_id"]]
                - positions[str(key_item["duplicate_of_trial_id"])]
            )
            for _, key_item in paired_trials
            if key_item.get("duplicate_of_trial_id")
        ]
        if all(distance >= minimum_repeat_distance for distance in repeat_distances):
            break
    else:  # pragma: no cover - only reachable for pathological tiny bundles
        raise RuntimeError("could not separate hidden repeats from their originals")
    public_trials = [item[0] for item in paired_trials]
    key_trials = [item[1] for item in paired_trials]
    public = {
        "schema": "scene_dna_blind_trials_v1",
        "method_labels_hidden": True,
        "scores_hidden": True,
        "left_right_randomized": True,
        "choices": sorted(CHOICES),
        "axes": list(AXES),
        "review_image_standardization": {
            "schema": "scene_dna_review_image_standardization_v1",
            "precomposited_rgb": True,
            "background_rgb": list(DEFAULT_REVIEW_BACKGROUND_RGB),
            "chroma_spill_qa_required": True,
        },
        "trials": public_trials,
    }
    key = {
        "schema": "scene_dna_blind_trial_key_v1",
        "must_not_be_served_to_reviewers": True,
        "random_seed": random_seed,
        "hidden_repeat_fraction": float(duplicate_fraction),
        "hidden_repeat_count": duplicate_count,
        "trials": key_trials,
    }
    write_json(output_dir / "trials.json", public)
    write_json(sealed_key_path, key)
    (output_dir / "index.html").write_text(_HTML, encoding="utf-8")
    return public


def export_offline_bundle(
    bundle_dir: Path,
    output_path: Path,
    *,
    label: str = "blind_review",
) -> dict[str, Any]:
    """Write a self-contained blind-review page that needs no web server.

    Only the already-public trials and their anonymized images are embedded. The
    sealed method key remains outside the page. Answers are kept in browser local
    storage and exported as JSONL for the existing analysis command.
    """

    bundle_dir = bundle_dir.resolve()
    public = read_json(bundle_dir / "trials.json")
    trials = public.get("trials", [])
    if not isinstance(trials, list) or not trials:
        raise ValueError(f"no trials found in {bundle_dir / 'trials.json'}")
    embedded = json.loads(json.dumps(public))
    for trial in embedded["trials"]:
        object_zh, style_zh = _localized_requirements(
            str(trial.get("category") or ""),
            str(trial.get("object_requirement") or ""),
            str(trial.get("style_requirement") or ""),
        )
        trial["object_requirement_zh"] = object_zh
        trial["style_requirement_zh"] = style_zh
        for side in ("left", "right"):
            relative_path = Path(str(trial["assets"][side]["image_path"]))
            source = (bundle_dir / relative_path).resolve()
            if bundle_dir not in source.parents or not source.is_file():
                raise ValueError(f"invalid public asset path: {relative_path}")
            mime_type = mimetypes.guess_type(source.name)[0] or "image/png"
            encoded = base64.b64encode(source.read_bytes()).decode("ascii")
            trial["assets"][side]["image_path"] = (
                f"data:{mime_type};base64,{encoded}"
            )
    public_json = json.dumps(embedded, ensure_ascii=False, separators=(",", ":"))
    # Prevent user-provided requirement text from terminating the data script.
    public_json = public_json.replace("<", "\\u003c")
    page = _OFFLINE_HTML.replace("__TRIALS_JSON__", public_json).replace(
        "__BUNDLE_LABEL__", html.escape(label, quote=True)
    )
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return {
        "schema": "scene_dna_offline_blind_review_export_v1",
        "output_path": str(output_path),
        "label": label,
        "trial_count": len(trials),
        "embedded_image_count": len(trials) * 2,
        "size_bytes": output_path.stat().st_size,
        "sealed_key_embedded": False,
    }


def _bootstrap_interval(values: list[float], *, seed: int = 17) -> list[float]:
    if not values:
        return [0.0, 0.0]
    rng = random.Random(seed)
    means = []
    for _ in range(5000):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    return [round(means[124], 6), round(means[4874], 6)]


def analyze_responses(
    responses_path: Path,
    sealed_key_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    key = read_json(sealed_key_path)
    trial_keys = {item["trial_id"]: item for item in key.get("trials", [])}
    raw_lines = responses_path.read_text(encoding="utf-8").splitlines()
    responses = [json.loads(line) for line in raw_lines if line.strip()]
    flagged_responses = [
        response
        for response in responses
        if str(response.get("trial_quality_status") or "ok") == "flagged"
    ]
    axis_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for response in responses:
        if str(response.get("trial_quality_status") or "ok") == "flagged":
            continue
        trial = trial_keys.get(str(response.get("trial_id") or ""))
        if trial is None:
            continue
        for axis in AXES:
            choice = str(response.get(f"{axis}_choice") or "")
            if choice not in CHOICES:
                continue
            if choice in {"left", "right"}:
                method = str(trial["assets"][choice]["method"])
                value = 1.0 if method == "proposed" else 0.0
            elif choice == "tie":
                method = "tie"
                value = 0.5
            else:
                method = "neither"
                # "Neither" says that both candidates are unusable; it is not
                # an indifferent preference.  Keep it in quality/outcome and
                # repeat-consistency accounting, but exclude it from the
                # proposed-versus-baseline preference denominator.  This also
                # matches BLIND_REVIEW_PROTOCOL.md, which only preregisters a
                # half vote for an explicit tie.
                value = None
            axis_rows[axis].append(
                {
                    "trial_id": trial["trial_id"],
                    "independent_case_id": str(
                        trial.get("independent_case_id") or trial["trial_id"]
                    ),
                    "reviewer_id": str(response.get("reviewer_id") or "anonymous"),
                    "outcome": method,
                    "proposed_preference_value": value,
                }
            )
    axis_reports: dict[str, Any] = {}
    repeat_checks: list[bool] = []
    for axis, rows in axis_rows.items():
        by_trial: dict[str, list[float]] = defaultdict(list)
        by_reviewer_case: dict[tuple[str, str], list[str]] = defaultdict(list)
        counts = defaultdict(int)
        for row in rows:
            if row["proposed_preference_value"] is not None:
                by_trial[row["independent_case_id"]].append(
                    row["proposed_preference_value"]
                )
            counts[row["outcome"]] += 1
            by_reviewer_case[
                (row["reviewer_id"], row["independent_case_id"])
            ].append(row["outcome"])
        axis_repeat_checks = [
            outcomes[0] == outcome
            for outcomes in by_reviewer_case.values()
            if len(outcomes) >= 2
            for outcome in outcomes[1:]
        ]
        repeat_checks.extend(axis_repeat_checks)
        trial_values = [
            sum(values) / len(values) for values in by_trial.values() if values
        ]
        preference = sum(trial_values) / len(trial_values) if trial_values else 0.0
        axis_reports[axis] = {
            "independent_trial_count": len(by_trial),
            "rating_count": len(rows),
            "preference_rating_count": sum(
                row["proposed_preference_value"] is not None for row in rows
            ),
            "neither_excluded_from_preference_count": counts.get("neither", 0),
            "outcome_counts": dict(counts),
            "proposed_preference_rate_ties_half": round(preference, 6),
            "cluster_bootstrap_95pct_interval": _bootstrap_interval(trial_values),
            "hidden_repeat_comparison_count": len(axis_repeat_checks),
            "hidden_repeat_exact_agreement_rate": (
                round(sum(axis_repeat_checks) / len(axis_repeat_checks), 6)
                if axis_repeat_checks
                else None
            ),
        }
    primary_values = [
        axis_reports.get(axis, {}).get("proposed_preference_rate_ties_half", 0.0)
        for axis in ("semantic", "form")
        if axis in axis_reports
    ]
    primary = sum(primary_values) / len(primary_values) if primary_values else 0.0
    lower_bounds = [
        axis_reports.get(axis, {}).get("cluster_bootstrap_95pct_interval", [0.0])[0]
        for axis in ("semantic", "form")
        if axis in axis_reports
    ]
    report = {
        "schema": "scene_dna_blind_review_analysis_v2",
        "submitted_response_count": len(responses),
        "quality_flagged_response_count": len(flagged_responses),
        "quality_flagged_trials": [
            {
                "trial_id": str(item.get("trial_id") or ""),
                "reviewer_id": str(item.get("reviewer_id") or "anonymous"),
                "quality_issue_side": str(item.get("quality_issue_side") or "unspecified"),
                "quality_issue_reason": str(item.get("quality_issue_reason") or ""),
            }
            for item in flagged_responses
        ],
        "axes": axis_reports,
        "primary_semantic_form_preference_rate": round(primary, 6),
        "primary_gate_passed": bool(
            primary >= 0.60 and lower_bounds and min(lower_bounds) > 0.50
        ),
        "reviewer_repeat_exact_agreement_rate": (
            round(sum(repeat_checks) / len(repeat_checks), 6)
            if repeat_checks
            else None
        ),
        "default_pipeline_replacement_allowed": False,
        "limitations": [
            "independent sample size is the number of trials, not the number of reviewer ratings",
            "neither outcomes are reported as joint unusability and excluded from preference rates",
            "hard-structure non-regression must be joined from the automated benchmark report before promotion",
        ],
    }
    write_json(output_path, report)
    return report


def audit_bundle_chroma_spill(
    bundle_dir: Path,
    output_path: Path,
    *,
    sealed_key_path: Path | None = None,
) -> dict[str, Any]:
    """Read-only audit of the exact questionnaire images.

    Hidden repeats are excluded when a sealed key is supplied. Method summaries
    remain private because the output itself belongs with the sealed analysis.
    """

    bundle_dir = bundle_dir.resolve()
    public = read_json(bundle_dir / "trials.json")
    key_by_trial: dict[str, dict[str, Any]] = {}
    if sealed_key_path is not None:
        key = read_json(sealed_key_path)
        key_by_trial = {
            str(row["trial_id"]): row
            for row in key.get("trials", [])
            if isinstance(row, dict)
        }
    rows: list[dict[str, Any]] = []
    for trial in public.get("trials", []):
        if not isinstance(trial, dict):
            continue
        trial_id = str(trial.get("trial_id") or "")
        key_trial = key_by_trial.get(trial_id, {})
        if key_trial.get("duplicate_of_trial_id"):
            continue
        for side in ("left", "right"):
            asset = trial.get("assets", {}).get(side, {})
            relative = Path(str(asset.get("image_path") or ""))
            source = (bundle_dir / relative).resolve()
            if bundle_dir not in source.parents or not source.is_file():
                raise ValueError(f"invalid public asset path: {relative}")
            _, hygiene = clean_chromatic_alpha_edges(Image.open(source))
            method = str(
                key_trial.get("assets", {}).get(side, {}).get("method")
                or "hidden"
            )
            rows.append(
                {
                    "trial_id": trial_id,
                    "case_id": str(trial.get("case_id") or ""),
                    "category": str(trial.get("category") or "unknown"),
                    "side": side,
                    "method": method,
                    "anonymous_id": str(asset.get("anonymous_id") or ""),
                    "image_path": str(source),
                    "qa_ok": bool(hygiene.get("ok", True)),
                    "hygiene": hygiene,
                }
            )
    method_reports: dict[str, Any] = {}
    for method in sorted({str(row["method"]) for row in rows}):
        selected = [row for row in rows if row["method"] == method]
        method_reports[method] = {
            "image_count": len(selected),
            "failed_count": sum(not row["qa_ok"] for row in selected),
            "failure_reason_counts": dict(
                Counter(
                    reason
                    for row in selected
                    for reason in row["hygiene"].get("reasons", [])
                )
            ),
        }
    failed = [row for row in rows if not row["qa_ok"]]
    report = {
        "schema": "scene_dna_blind_bundle_chroma_audit_v1",
        "bundle_dir": str(bundle_dir),
        "sealed_key_used": sealed_key_path is not None,
        "hidden_repeats_excluded": sealed_key_path is not None,
        "source_images_modified": False,
        "independent_image_count": len(rows),
        "failed_image_count": len(failed),
        "strict_bundle_passed": not failed,
        "failure_reason_counts": dict(
            Counter(
                reason
                for row in failed
                for reason in row["hygiene"].get("reasons", [])
            )
        ),
        "method_reports_private": method_reports,
        "images": rows,
        "decision": (
            "eligible_for_new_blind_review"
            if not failed
            else "do_not_reuse_for_new_blind_review"
        ),
    }
    write_json(output_path, report)
    return report


def serve_bundle(bundle_dir: Path, *, host: str, port: int) -> None:
    bundle_dir = bundle_dir.resolve()
    responses_path = bundle_dir / "responses.jsonl"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            relative = "index.html" if self.path in {"/", ""} else self.path.lstrip("/")
            path = (bundle_dir / relative).resolve()
            if bundle_dir not in path.parents and path != bundle_dir:
                self.send_error(403)
                return
            if not path.is_file():
                self.send_error(404)
                return
            content_type = "text/html" if path.suffix == ".html" else "application/json" if path.suffix == ".json" else "image/png"
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/response":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            with responses_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer((host, port), Handler).serve_forever()


_HTML = """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SceneDNA 中文盲评</title>
<style>body{font:16px sans-serif;max-width:1200px;margin:24px auto;background:#eee} .pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pair img{width:100%;background:#ddd}.axes{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}button{padding:10px;margin:2px}.chosen{outline:3px solid #2674ff}</style>
<h1>SceneDNA 匿名资产比较</h1><p>请只根据图片和题目要求独立判断。拖鞋题按单只鞋评价，不要求生成一双。</p><label>评审编号：<input id="reviewer" placeholder="例如 reviewer_02"></label><p id="requirement"></p><div class="pair"><div><h2>A</h2><img id="left" alt="匿名候选 A"></div><div><h2>B</h2><img id="right" alt="匿名候选 B"></div></div><div id="axes" class="axes"></div><button id="submit">提交本题并继续</button><span id="progress"></span>
<script>
let trials=[], index=0, answers={}, trialStartedAt=0; const choices=[['left','A 更好'],['right','B 更好'],['tie','同等合格'],['neither','都不合格']]; const axes=[['semantic','语义：像不像要求的物体'],['form','形态：结构和部件是否正确'],['style','风格：是否符合风格要求'],['overall','整体：综合更愿意使用哪个']];
fetch('trials.json').then(r=>r.json()).then(x=>{trials=x.trials; show()});
function show(){let t=trials[index]; answers={}; trialStartedAt=performance.now(); requirement.textContent='物体要求：'+(t.object_requirement_zh||t.object_requirement)+'｜风格要求：'+(t.style_requirement_zh||t.style_requirement); left.src=t.assets.left.image_path; right.src=t.assets.right.image_path; axesDiv=document.getElementById('axes'); axesDiv.innerHTML=''; axes.forEach(([axis,title])=>{let d=document.createElement('div');d.innerHTML='<b>'+title+'</b><br>';choices.forEach(([choice,label])=>{let b=document.createElement('button');b.textContent=label;b.onclick=()=>{answers[axis]=choice;[...d.querySelectorAll('button')].forEach(x=>x.classList.remove('chosen'));b.classList.add('chosen')};d.appendChild(b)});axesDiv.appendChild(d)});progress.textContent='第 '+(index+1)+' / '+trials.length+' 题'}
submit.onclick=async()=>{if(!reviewer.value.trim()){alert('请先填写稳定的评审编号，例如 reviewer_02');reviewer.focus();return}if(axes.some(([axis])=>!answers[axis])){alert('请完成四个维度的选择');return}let t=trials[index];let payload={trial_id:t.trial_id,reviewer_id:reviewer.value.trim(),elapsed_seconds:Math.round((performance.now()-trialStartedAt)/10)/100};axes.forEach(([axis])=>payload[axis+'_choice']=answers[axis]);await fetch('/api/response',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});index++;if(index>=trials.length){document.body.innerHTML='<h1>评审完成</h1><p>感谢完成全部题目。</p>'}else show()};
</script></html>"""


_OFFLINE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SceneDNA 离线盲评</title>
<style>
:root{color-scheme:light;font-family:Arial,"Microsoft YaHei",sans-serif}
body{max-width:1240px;margin:20px auto;padding:0 18px;background:#f2f3f5;color:#202124}
h1{margin-bottom:8px}.notice{background:#fff5d6;border:1px solid #e2c66a;padding:10px 14px;border-radius:8px}
.toolbar,.status{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:14px 0}
input{padding:8px;font-size:16px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.card{background:white;padding:12px;border-radius:10px;box-shadow:0 1px 4px #0002}.card img{display:block;width:100%;height:auto;background:#ddd}
.axes{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}.axis{background:white;padding:10px;border-radius:8px}
button{padding:9px 12px;margin:3px;border:1px solid #999;border-radius:6px;background:white;cursor:pointer}
button:hover{background:#edf3ff}.chosen{outline:3px solid #2674ff;background:#e7efff}.primary{background:#1769e0;color:white;border-color:#1769e0}
.complete{background:white;padding:28px;border-radius:10px;text-align:center}.muted{color:#666}
@media(max-width:800px){.pair,.axes{grid-template-columns:1fr}.card img{max-height:none}}
</style>
</head>
<body>
<h1>SceneDNA 离线匿名资产比较</h1>
<p class="notice">页面不连接服务器，也不包含方法标签或密钥。请独立判断，不要查看源文件或刷新后更换评审编号。拖鞋题按单只鞋本身评价，不要求生成一双。</p>
<div class="toolbar">
  <label>评审编号：<input id="reviewer" placeholder="例如 reviewer_01"></label>
  <button id="download">导出当前结果 JSONL</button>
  <button id="reset">清除本页进度</button>
</div>
<div id="review">
  <div class="status"><strong id="progress"></strong><span id="saved" class="muted"></span></div>
  <p id="requirement"></p>
  <div class="pair">
    <div class="card"><h2>A</h2><img id="left" alt="匿名候选 A"></div>
    <div class="card"><h2>B</h2><img id="right" alt="匿名候选 B"></div>
  </div>
  <div id="axes" class="axes"></div>
  <p id="imageWarning" class="notice" hidden></p>
  <button id="submit" class="primary">提交本题并继续</button>
  <button id="flag">图片异常，跳过本题</button>
  <button id="back">返回上一题重做</button>
</div>
<div id="complete" class="complete" hidden>
  <h2>本评审包已完成</h2>
  <p>请下载结果文件，并将 <code>responses.jsonl</code> 交给实验负责人。</p>
  <button id="downloadFinal" class="primary">下载最终结果 JSONL</button>
</div>
<script id="trial-data" type="application/json">__TRIALS_JSON__</script>
<script>
const bundleLabel="__BUNDLE_LABEL__";
const publicData=JSON.parse(document.getElementById('trial-data').textContent);
const trials=publicData.trials;
const choices=[['left','A 更好'],['right','B 更好'],['tie','同等合格'],['neither','都不合格']];
const axes=[['semantic','语义：像不像要求的物体'],['form','形态：结构和部件是否正确'],['style','风格：是否符合风格要求'],['overall','整体：综合更愿意使用哪个']];
const fingerprint=trials.map(t=>t.trial_id).join('|');
const storageKey='scene_dna_offline_v1:'+bundleLabel+':'+fingerprint.length+':'+fingerprint.slice(0,32);
let state={index:0,responses:[],reviewerId:''};
let answers={};let trialStartedAt=performance.now();let imageFailures=[];
try{const savedState=localStorage.getItem(storageKey);if(savedState)state=JSON.parse(savedState)}catch(error){}
const reviewer=document.getElementById('reviewer');reviewer.value=state.reviewerId||'';
function persist(){state.reviewerId=reviewer.value.trim();try{localStorage.setItem(storageKey,JSON.stringify(state));saved.textContent='进度已保存在本机浏览器'}catch(error){saved.textContent='浏览器禁止自动保存，请及时导出结果'}}
reviewer.addEventListener('change',persist);
function show(){
  if(state.index>=trials.length){review.hidden=true;complete.hidden=false;return}
  review.hidden=false;complete.hidden=true;answers={};imageFailures=[];imageWarning.hidden=true;trialStartedAt=performance.now();
  const t=trials[state.index];progress.textContent='第 '+(state.index+1)+' / '+trials.length+' 题';
  requirement.textContent='物体要求：'+(t.object_requirement_zh||t.object_requirement)+'｜风格要求：'+(t.style_requirement_zh||t.style_requirement);
  [['A',left,t.assets.left.image_path],['B',right,t.assets.right.image_path]].forEach(([label,img,path])=>{img.onload=()=>{};img.onerror=()=>{imageFailures.push(label);imageWarning.textContent='候选 '+label+' 图片加载失败，请使用“图片异常，跳过本题”记录问题。';imageWarning.hidden=false};img.src=path});
  const axesDiv=document.getElementById('axes');axesDiv.innerHTML='';
  axes.forEach(([axis,title])=>{const d=document.createElement('div');d.className='axis';const heading=document.createElement('strong');heading.textContent=title;d.appendChild(heading);d.appendChild(document.createElement('br'));
    choices.forEach(([choice,label])=>{const b=document.createElement('button');b.textContent=label;b.onclick=()=>{answers[axis]=choice;d.querySelectorAll('button').forEach(x=>x.classList.remove('chosen'));b.classList.add('chosen')};d.appendChild(b)});axesDiv.appendChild(d)});
  persist();
  reviewer.disabled=state.responses.length>0;back.disabled=state.index===0;
}
function downloadResponses(){
  if(!state.responses.length){alert('当前还没有已提交的答案');return}
  const content=state.responses.map(row=>JSON.stringify(row)).join('\\n')+'\\n';
  const blob=new Blob([content],{type:'application/x-ndjson;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');
  const id=(reviewer.value.trim()||'anonymous').replace(/[^a-zA-Z0-9_-]/g,'_');a.href=url;a.download=bundleLabel+'_'+id+'_responses.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
submit.onclick=()=>{
  const reviewerId=reviewer.value.trim();if(!reviewerId){alert('请先填写稳定的评审编号，例如 reviewer_01');reviewer.focus();return}
  if(axes.some(([axis])=>!answers[axis])){alert('请完成四个维度的选择');return}
  if(imageFailures.length){alert('存在图片加载失败，请标记图片异常，不要强制作答');return}
  const t=trials[state.index];const payload={trial_id:t.trial_id,reviewer_id:reviewerId,trial_quality_status:'ok',elapsed_seconds:Math.round((performance.now()-trialStartedAt)/10)/100};
  axes.forEach(([axis])=>payload[axis+'_choice']=answers[axis]);state.responses.push(payload);state.index++;persist();show();
};
flag.onclick=()=>{
  const reviewerId=reviewer.value.trim();if(!reviewerId){alert('请先填写稳定的评审编号');reviewer.focus();return}
  const side=(prompt('哪一侧图片异常？请输入 A、B 或 BOTH')||'unspecified').trim().toUpperCase();
  const reason=(prompt('请简要说明异常，例如：下半部分缺失、图片未加载、主体被裁切')||'reviewer_flagged_image_issue').trim();
  const t=trials[state.index];state.responses.push({trial_id:t.trial_id,reviewer_id:reviewerId,trial_quality_status:'flagged',quality_issue_side:side,quality_issue_reason:reason,elapsed_seconds:Math.round((performance.now()-trialStartedAt)/10)/100});state.index++;persist();show();
};
back.onclick=()=>{if(state.index<=0)return;state.index--;state.responses.pop();persist();show()};
download.onclick=downloadResponses;downloadFinal.onclick=downloadResponses;
reset.onclick=()=>{if(confirm('确定清除这个评审包在本浏览器中的全部进度吗？')){state={index:0,responses:[],reviewerId:reviewer.value.trim()};persist();show()}};
show();
</script>
</body>
</html>"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--comparisons", required=True, type=Path)
    prepare.add_argument("--output-dir", required=True, type=Path)
    prepare.add_argument("--sealed-key", required=True, type=Path)
    prepare.add_argument("--random-seed", type=int, default=20260823)
    prepare.add_argument("--duplicate-fraction", type=float, default=0.10)
    serve = sub.add_parser("serve")
    serve.add_argument("--bundle-dir", required=True, type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8094)
    offline = sub.add_parser("export-offline")
    offline.add_argument("--bundle-dir", required=True, type=Path)
    offline.add_argument("--output", required=True, type=Path)
    offline.add_argument("--label", default="blind_review")
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--responses", required=True, type=Path)
    analyze.add_argument("--sealed-key", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    audit = sub.add_parser("audit-images")
    audit.add_argument("--bundle-dir", required=True, type=Path)
    audit.add_argument("--sealed-key", type=Path)
    audit.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "prepare":
        prepare_blind_bundle(
            args.comparisons,
            args.output_dir,
            sealed_key_path=args.sealed_key,
            random_seed=int(args.random_seed),
            duplicate_fraction=float(args.duplicate_fraction),
        )
    elif args.command == "serve":
        serve_bundle(args.bundle_dir, host=str(args.host), port=int(args.port))
    elif args.command == "export-offline":
        report = export_offline_bundle(
            args.bundle_dir, args.output, label=str(args.label)
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == "analyze":
        analyze_responses(args.responses, args.sealed_key, args.output)
    else:
        report = audit_bundle_chroma_spill(
            args.bundle_dir,
            args.output,
            sealed_key_path=args.sealed_key,
        )
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "schema",
                        "independent_image_count",
                        "failed_image_count",
                        "strict_bundle_passed",
                        "failure_reason_counts",
                        "method_reports_private",
                        "decision",
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
