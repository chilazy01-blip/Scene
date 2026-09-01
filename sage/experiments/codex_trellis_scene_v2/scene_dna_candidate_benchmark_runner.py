from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .io_utils import read_json, write_json


def _opener():
    return urlrequest.build_opener(urlrequest.ProxyHandler({}))


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urlrequest.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _opener().open(request, timeout=30.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_json(url: str, *, timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with _opener().open(url, timeout=60.0) as response:
                content_type = str(response.headers.get("Content-Type") or "")
                body = response.read()
                if response.status == 200:
                    if "json" not in content_type:
                        raise RuntimeError(
                            f"candidate-only job returned {content_type}, expected JSON"
                        )
                    return json.loads(body.decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 500:
                raise RuntimeError(exc.read().decode("utf-8", errors="replace"))
            if exc.code not in {202, 404}:
                raise
        except (TimeoutError, URLError, ConnectionError):
            # A bridge that is loading RMBG/SigLIP can temporarily hold the
            # interpreter longer than one HTTP read timeout.  The batch-level
            # deadline remains authoritative; a single slow poll is not a
            # failed generation and must not create an infrastructure reject.
            pass
        time.sleep(2.0)
    raise TimeoutError(f"candidate batch timed out after {timeout}s")


def _legacy_score(attempt: dict[str, Any]) -> float:
    score = attempt.get("scene_dna_candidate_score")
    score = score if isinstance(score, dict) else {}
    return float(score.get("legacy_pixel_score", score.get("score", 0.0)) or 0.0)


def is_retryable_infrastructure_failure(error: object) -> bool:
    """Separate interrupted services from legitimate model/quality rejection."""

    normalized = str(error or "").lower()
    return any(
        marker in normalized
        for marker in (
            "timeouterror",
            "timed out",
            "connectionerror",
            "connection refused",
            "connection reset",
            "remote end closed",
            "temporarily unavailable",
            "service unavailable",
            "no module named 'diffusers'",
            'no module named "diffusers"',
        )
    )


def run_candidate_benchmark(
    plan_path: Path,
    output_dir: Path,
    *,
    bridge_url: str,
    limit: int | None = None,
    start_index: int = 0,
    one_per_category: bool = False,
    timeout: float = 1200.0,
    resume: bool = True,
    retry_failures: bool = False,
    retry_infrastructure_failures: bool = False,
) -> dict[str, Any]:
    plan = read_json(plan_path)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_rows = plan.get("batches", [])
    if one_per_category:
        sampled: list[dict[str, Any]] = []
        seen: set[str] = set()
        for batch in batch_rows:
            category = str(batch.get("category") or "")
            if category in seen:
                continue
            seen.add(category)
            sampled.append(batch)
        batch_rows = sampled
    batch_rows = batch_rows[max(0, int(start_index)) :]
    if limit is not None:
        batch_rows = batch_rows[: max(0, int(limit))]
    results: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    for index, batch in enumerate(batch_rows):
        case_id = str(batch["case_id"])
        case_dir = output_dir / "cases" / case_id
        result_path = case_dir / "candidate_batch_result.json"
        failure_path = case_dir / "candidate_batch_failure.json"
        if (
            resume
            and failure_path.is_file()
            and not result_path.is_file()
        ):
            failure = read_json(failure_path)
            should_retry = bool(retry_failures) or bool(
                retry_infrastructure_failures
                and is_retryable_infrastructure_failure(failure.get("error"))
            )
            if should_retry:
                failure = None
            else:
                results.append(
                    {
                        "case_id": case_id,
                        "category": batch["category"],
                        "style_condition": batch["style_condition"],
                        "shape_profile": batch["semantic_form_contract"]["shape_profile"],
                        "batch_seed": batch["batch_seed"],
                        "status": "batch_rejected_or_failed",
                        "error": read_json(failure_path).get("error"),
                        "selection_changed": False,
                        "promoted_reference_job_ids": [],
                        "candidate_count": 0,
                    }
                )
                print(
                    f"[{index + 1}/{len(batch_rows)}] {case_id} "
                    "status=batch_rejected_or_failed",
                    flush=True,
                )
                continue
        if resume and result_path.is_file():
            bridge_result = read_json(result_path)
        else:
            scene_dna = {
                "contract_hash": hashlib.sha256(
                    json.dumps(batch, sort_keys=True).encode("utf-8")
                ).hexdigest(),
                "global_tags": str(batch["style_condition"]).split("_"),
                "individuality_tags": [],
                "semantic_form_contract": batch["semantic_form_contract"],
                "candidate_funnel": {
                    "isolated_2d_candidates": int(batch["candidate_count"]),
                    "max_candidates_promoted_to_trellis2": 2,
                },
            }
            try:
                accepted = _post_json(
                    bridge_url.rstrip("/") + "/generate",
                    {
                        "input_text": batch["object_prompt"],
                        "seed": int(batch["batch_seed"]),
                        "candidate_only": True,
                        "scene_dna": scene_dna,
                        "scene_dna_candidate_count": int(batch["candidate_count"]),
                    },
                )
                bridge_result = _wait_json(
                    bridge_url.rstrip("/") + f"/job/{accepted['job_id']}",
                    timeout=timeout,
                )
            except Exception as exc:
                case_dir.mkdir(parents=True, exist_ok=True)
                failure = {
                    "schema": "scene_dna_candidate_batch_failure_v1",
                    "case_id": case_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                write_json(failure_path, failure)
                results.append(
                    {
                        "case_id": case_id,
                        "category": batch["category"],
                        "style_condition": batch["style_condition"],
                        "shape_profile": batch["semantic_form_contract"]["shape_profile"],
                        "batch_seed": batch["batch_seed"],
                        "status": "batch_rejected_or_failed",
                        "error": failure["error"],
                        "selection_changed": False,
                        "promoted_reference_job_ids": [],
                        "candidate_count": 0,
                    }
                )
                print(
                    f"[{index + 1}/{len(batch_rows)}] {case_id} "
                    "status=batch_rejected_or_failed",
                    flush=True,
                )
                continue
            case_dir.mkdir(parents=True, exist_ok=True)
            write_json(result_path, bridge_result)
        attempts = [
            item
            for item in bridge_result.get("reference_attempts", [])
            if isinstance(item, dict) and item.get("prepared_image_path")
        ]
        copied: dict[str, str] = {}
        for attempt in attempts:
            source = Path(str(attempt["prepared_image_path"]))
            destination = case_dir / f"candidate_{int(attempt.get('attempt', 0)):02d}.png"
            if source.is_file() and not destination.is_file():
                shutil.copy2(source, destination)
            copied[str(attempt.get("reference_job_id") or "")] = str(destination)
        legacy = max(attempts, key=_legacy_score)
        proposed_id = str(bridge_result.get("selected_reference_job_id") or "")
        proposed = next(
            (
                item
                for item in attempts
                if str(item.get("reference_job_id") or "") == proposed_id
            ),
            max(
                attempts,
                key=lambda item: float(
                    item.get("scene_dna_candidate_score", {}).get("score", 0.0)
                ),
            ),
        )
        legacy_id = str(legacy.get("reference_job_id") or "")
        selection = bridge_result.get("scene_dna_candidate_selection") or {}
        row = {
            "case_id": case_id,
            "category": batch["category"],
            "style_condition": batch["style_condition"],
            "shape_profile": batch["semantic_form_contract"]["shape_profile"],
            "batch_seed": batch["batch_seed"],
            "legacy_selected_reference_job_id": legacy_id,
            "proposed_selected_reference_job_id": proposed_id,
            "selection_changed": legacy_id != proposed_id,
            "legacy_selected_score": _legacy_score(legacy),
            "proposed_selected_score": float(
                proposed.get("scene_dna_candidate_score", {}).get("score", 0.0)
            ),
            "uncertainty": selection.get("uncertainty"),
            "promoted_reference_job_ids": selection.get(
                "promoted_reference_job_ids", []
            ),
            "candidate_count": len(attempts),
            "candidate_result_path": str(result_path),
        }
        results.append(row)
        if legacy_id != proposed_id:
            comparisons.append(
                {
                    "case_id": case_id,
                    "category": batch["category"],
                    "shape_profile": batch["semantic_form_contract"]["shape_profile"],
                    "object_requirement": batch["object_prompt"],
                    "style_requirement": batch["style_condition"],
                    "baseline": {
                        "asset_id": legacy_id,
                        "image_path": copied[legacy_id],
                    },
                    "proposed": {
                        "asset_id": proposed_id,
                        "image_path": copied[proposed_id],
                    },
                }
            )
        print(
            f"[{index + 1}/{len(batch_rows)}] {case_id} "
            f"changed={legacy_id != proposed_id} promoted={len(row['promoted_reference_job_ids'])}",
            flush=True,
        )
    changed = sum(bool(item["selection_changed"]) for item in results)
    summary = {
        "schema": "scene_dna_candidate_benchmark_results_v1",
        "plan_path": str(plan_path.resolve()),
        "completed_batch_count": len(results),
        "rejected_or_failed_batch_count": sum(
            item.get("status") == "batch_rejected_or_failed" for item in results
        ),
        "selection_changed_count": changed,
        "selection_change_rate": round(changed / max(1, len(results)), 6),
        "uncertain_top2_count": sum(
            len(item.get("promoted_reference_job_ids", [])) >= 2
            for item in results
        ),
        "results": results,
        "limitations": [
            "candidate ranking alone is not a visual-improvement claim",
            "changed selections require the sealed blind review and stratified 3D follow-up",
        ],
    }
    write_json(output_dir / "candidate_benchmark_results.json", summary)
    write_json(
        output_dir / "blind_comparisons.json",
        {"schema": "scene_dna_blind_comparisons_v1", "comparisons": comparisons},
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8082")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument(
        "--one-per-category",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--timeout", type=float, default=1200.0)
    parser.add_argument(
        "--resume", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--retry-failures",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Retry previously recorded failed batches while preserving completed batches.",
    )
    parser.add_argument(
        "--retry-infrastructure-failures",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Retry only timeout/connection failures while preserving completed "
            "batches and legitimate quality-gate rejections."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_candidate_benchmark(
        args.plan,
        args.output_dir,
        bridge_url=str(args.bridge_url),
        limit=args.limit,
        start_index=int(args.start_index),
        one_per_category=bool(args.one_per_category),
        timeout=float(args.timeout),
        resume=bool(args.resume),
        retry_failures=bool(args.retry_failures),
        retry_infrastructure_failures=bool(args.retry_infrastructure_failures),
    )
    print(
        json.dumps(
            {
                "completed_batch_count": report["completed_batch_count"],
                "selection_change_rate": report["selection_change_rate"],
                "uncertain_top2_count": report["uncertain_top2_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
