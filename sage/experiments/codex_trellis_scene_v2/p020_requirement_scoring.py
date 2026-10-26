"""P020 atomic predictions and consensus; no calibration or asset acceptance.

The test-time design is fixed: A uses one frozen SigLIP batch of contrastive
prompts, C preserves disagreements, and deterministic source rules come only
from runner evidence. This module never inspects heldout labels or learns weights.
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from .content_chain import content_hash
from .native_alpha_normalization import visible_white_rgb, write_immutable
from .scene_dna_semantic import Siglip2SemanticScorer

SCHEMA = "scene-v2-p020-requirement-predictions/v1"
RUNNER_SCHEMA = "scene-v2-p020-trusted-runner-evidence/v1"
PASS_THRESHOLD = 0.8
FAIL_THRESHOLD = 0.2
VERDICTS = {"pass", "fail", "unknown"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Boolean positive means question=true, negative means question=false.

    expected=False reverses compliance polarity. For int/string expected values,
    positive describes that expected value and negative a nonmatching contrast.
    """
    requirements = deepcopy(contract.get("requirements"))
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("contract requires a nonempty requirements list")
    seen: set[str] = set()
    for row in requirements:
        if not isinstance(row, dict):
            raise ValueError("each requirement must be an object")
        for key in ("id", "question", "positive", "negative"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"requirement {key} must be a nonempty string")
        if row["id"] in seen:
            raise ValueError("requirement IDs must be unique")
        seen.add(row["id"])
        if type(row.get("expected")) not in (bool, int, str):
            raise ValueError("expected must have exact bool, int or str type")
        if type(row.get("hard")) is not bool:
            raise ValueError("hard must be boolean")
        if not isinstance(row.get("depends_on"), list) or any(not isinstance(item, str) for item in row["depends_on"]):
            raise ValueError("depends_on must be a list of requirement IDs")
        if len(set(row["depends_on"])) != len(row["depends_on"]):
            raise ValueError("duplicate requirement dependency")
    by_id = {row["id"]: row for row in requirements}
    completed: set[str] = set()

    def visit(key: str, parents: set[str]) -> None:
        if key not in by_id:
            raise ValueError("dependency references an unknown requirement")
        if key in parents:
            raise ValueError("requirement dependencies contain a cycle")
        if key not in completed:
            for parent in by_id[key]["depends_on"]:
                visit(parent, parents | {key})
            completed.add(key)

    for row in requirements:
        visit(row["id"], set())
    return requirements


@dataclass(frozen=True)
class RunnerEvidence:
    """Runner-side trust boundary; never construct from a model's response.

    The normal loader verifies an independently supplied manifest SHA and image
    SHA. A trusted orchestration caller may also construct this in memory.
    """
    image_sha256: str
    source: bool | None
    alpha: bool | None
    binding: dict[str, Any]

    def __post_init__(self) -> None:
        if any(type(value) not in (bool, type(None)) for value in (self.source, self.alpha)):
            raise ValueError("source/alpha runner rules must be bool or null")
        if len(self.image_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.image_sha256):
            raise ValueError("runner evidence must bind an image SHA-256")
        if not isinstance(self.binding, dict) or not self.binding:
            raise ValueError("runner evidence needs a provenance binding")


def load_runner_evidence(path: Path, *, expected_sha256: str, image_path: Path) -> RunnerEvidence:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise ValueError("runner evidence manifest SHA mismatch")
    record = json.loads(raw)
    image_sha = _sha(image_path)
    if record.get("schema") != RUNNER_SCHEMA or record.get("image_sha256") != image_sha:
        raise ValueError("runner evidence schema or image binding mismatch")
    rules = record.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("runner rules must be an object")
    return RunnerEvidence(image_sha, rules.get("source"), rules.get("alpha"), {"path": str(path.resolve()), "sha256": digest, "schema": RUNNER_SCHEMA})


def _source_rules(evidence: RunnerEvidence | None, image_sha256: str | None = None, *, prior_reports: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if evidence is not None and not isinstance(evidence, RunnerEvidence):
        raise TypeError("source rules accept only typed trusted runner evidence")
    if evidence and image_sha256 and evidence.image_sha256 != image_sha256:
        raise ValueError("runner evidence belongs to a different source image")
    rules = [{"id": key, "hard": True, "verdict": "unknown" if evidence is None or getattr(evidence, key) is None else ("pass" if getattr(evidence, key) else "fail"), "kind": "deterministic_runner_rule", "reason": "runner_evidence_missing" if evidence is None else "trusted_runner_evidence", "binding": deepcopy(evidence.binding) if evidence else None} for key in ("source", "alpha")]
    expected_image = image_sha256 or (evidence.image_sha256 if evidence else None)
    for report in prior_reports or []:
        # Preserve runner vetoes from this module's A/C reports. A model's B
        # response/source claims are never a source of deterministic credit.
        if report.get("schema") != SCHEMA or report.get("method") not in {"A", "C"}:
            continue
        bound_image = report.get("image_binding", {}).get("source_sha256") or report.get("source_image_sha256")
        for serialized in [report.get("runner_evidence"), *report.get("retained_runner_evidence", [])]:
            if not isinstance(serialized, dict):
                continue
            prior = RunnerEvidence(**serialized)
            if not bound_image or bound_image != prior.image_sha256:
                raise ValueError("prior runner evidence lacks its matching image binding")
            if expected_image and prior.image_sha256 != expected_image:
                raise ValueError("cannot merge runner evidence for different images")
            expected_image = prior.image_sha256
            for rule in rules:
                if getattr(prior, rule["id"]) is False:
                    rule.update(verdict="fail", reason="retained_trusted_runner_failure")
                    rule.setdefault("retained_failure_bindings", []).append(deepcopy(prior.binding))
    return rules


def standardized_white_image(image_path: Path, output_dir: Path) -> tuple[Image.Image, dict[str, Any]]:
    source_sha = _sha(image_path)
    with Image.open(image_path) as source:
        original_mode, original_size = source.mode, list(source.size)
        orientation = source.getexif().get(274)
        rgba = np.asarray(ImageOps.exif_transpose(source).convert("RGBA"), dtype=np.uint8)
    # Same full-frame alpha composition for every requirement. No cropping,
    # connected-component/hole heuristics, or semantic inference from alpha.
    image = Image.fromarray(visible_white_rgb(rgba), "RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    destination = output_dir / f"p020_white_{source_sha}.png"
    write_immutable(destination, buffer.getvalue())
    if _sha(image_path) != source_sha:
        raise ValueError("source image changed during normalization")
    return image, {"source_path": str(image_path.resolve()), "source_sha256": source_sha, "original_mode": original_mode, "original_size": original_size, "source_exif_orientation": orientation, "normalized_path": str(destination.resolve()), "normalized_sha256": _sha(destination), "display_pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(), "normalization": "exif-transpose/straight-alpha-u8-white-round-half-up/full-frame/v1", "source_modified": False, "size": list(image.size)}


def _dependent_rows(requirements: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["id"]: deepcopy(row) for row in rows}
    contract = {row["id"]: row for row in requirements}
    complete: set[str] = set()

    def visit(key: str) -> None:
        if key in complete:
            return
        for parent in contract[key]["depends_on"]:
            visit(parent)
        blocked = [parent for parent in contract[key]["depends_on"] if by_id[parent]["verdict"] != "pass"]
        if blocked:
            by_id[key].update(raw_verdict=by_id[key].get("raw_verdict", by_id[key]["verdict"]), verdict="unknown", blocked_by=blocked, reason="blocked_unknown")
        else:
            by_id[key].setdefault("blocked_by", [])
        complete.add(key)

    for row in requirements:
        visit(row["id"])
    return [by_id[row["id"]] for row in requirements]


def _prediction_verdict(rows: list[dict[str, Any]], rules: list[dict[str, Any]]) -> str:
    verdicts = [row["verdict"] for row in [*rules, *rows] if row.get("hard", True) and not row.get("blocked_by")]
    return "fail" if "fail" in verdicts else ("unknown" if "unknown" in verdicts else "pass")


class AtomicSiglipScorer:
    def __init__(self, model_name_or_path: str = "", *, device: str = "cpu", scorer: Any = None) -> None:
        self.scorer = scorer if scorer is not None else Siglip2SemanticScorer(model_name_or_path, device=device)

    def score(self, image_path: Path, contract: dict[str, Any], *, output_dir: Path, runner_evidence: RunnerEvidence | None = None) -> dict[str, Any]:
        requirements = validate_contract(contract)
        image, binding = standardized_white_image(image_path, output_dir)
        rules = _source_rules(runner_evidence, binding["source_sha256"])
        prompts = [row[key] for row in requirements for key in ("positive", "negative")]
        logits = self.scorer._logits(image, prompts)  # Exactly one image/text batch.
        well_formed = isinstance(logits, (list, tuple)) and len(logits) == len(prompts)
        rows = []
        for index, requirement in enumerate(requirements):
            positive, negative, margin, raw_margin, contrast = (None,) * 5
            if well_formed:
                try:
                    positive, negative = float(logits[2 * index]), float(logits[2 * index + 1])
                    if not math.isfinite(positive) or not math.isfinite(negative):
                        raise ValueError("nonfinite logits")
                    raw_margin = positive - negative
                    # Boolean prompts assert/deny the question. For nonbooleans,
                    # positive names the expected value and negative its contrast.
                    margin = -raw_margin if requirement["expected"] is False else raw_margin
                    contrast = 1 / (1 + math.exp(-margin)) if margin >= 0 else math.exp(margin) / (1 + math.exp(margin))
                except (ValueError, TypeError, OverflowError):
                    positive, negative, margin, raw_margin, contrast = (None,) * 5
            verdict = "unknown" if contrast is None else ("pass" if contrast >= PASS_THRESHOLD else "fail" if contrast <= FAIL_THRESHOLD else "unknown")
            rows.append({**requirement, "verdict": verdict, "verdict_kind": "uncalibrated_prediction", "positive_logit": positive, "negative_logit": negative, "raw_margin": raw_margin, "margin": margin, "contrast_score": contrast, "contrast_score_calibrated": False, "reason": "logits_unavailable" if contrast is None else "fixed_uncalibrated_contrast_thresholds"})
        rows = _dependent_rows(requirements, rows)
        return {"schema": SCHEMA, "method": "A", "contract_hash": content_hash(contract), "prompt_polarity": {"bool": "positive=question_true; negative=question_false; expected_false_flips_margin", "int_or_str": "positive=expected_value; negative=nonmatching_value"}, "requirements": rows, "source_rules": rules, "runner_evidence": asdict(runner_evidence) if runner_evidence else None, "image_binding": binding, "verdict": _prediction_verdict(rows, rules), "verdict_kind": "uncalibrated_prediction", "accepted": False, "asset_accepted": False, "thresholds": {"pass_at_or_above": PASS_THRESHOLD, "fail_at_or_below": FAIL_THRESHOLD, "fixed_before_heldout": True}, "model_calls": 1}

    def close(self) -> None:
        self.scorer.close()


def consensus(contract: dict[str, Any], report_a: dict[str, Any] | None, report_b: dict[str, Any] | None, *, runner_evidence: RunnerEvidence | None = None) -> dict[str, Any]:
    requirements = validate_contract(contract)
    reports = {"A": report_a or {}, "B": report_b or {}}
    contract_hash = content_hash(contract)
    for report in reports.values():
        if report.get("contract_hash") and report["contract_hash"] != contract_hash:
            raise ValueError("report contract hash mismatch")
    image_a = reports["A"].get("image_binding", {}).get("source_sha256")
    image_b = reports["B"].get("image", {}).get("sha256")
    if image_a and image_b and image_a != image_b:
        raise ValueError("A and B reports belong to different original images")
    if runner_evidence and any(value and value != runner_evidence.image_sha256 for value in (image_a, image_b)):
        raise ValueError("A/B image binding differs from runner evidence")
    mappings = {}
    for name, report in reports.items():
        mapping = {}
        for row in report.get("requirements", []):
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                key = row["id"]
                mapping[key] = deepcopy(row) if key not in mapping else {"id": key, "verdict": "unknown", "reason": "duplicate_requirement_id", "raw_rows": [mapping[key], deepcopy(row)]}
        mappings[name] = mapping
    rows = []
    for requirement in requirements:
        key = requirement["id"]
        evidence = {name: deepcopy(mapping.get(key)) for name, mapping in mappings.items()}
        for row in evidence.values():
            if isinstance(row, dict) and "expected" in row and (type(row["expected"]) is not type(requirement["expected"]) or row["expected"] != requirement["expected"]):
                row.update(raw_verdict=row.get("verdict"), verdict="unknown", reason="contract_expected_mismatch")
        if image_a and not image_b and evidence["B"]:
            evidence["B"].update(raw_verdict=evidence["B"].get("verdict"), verdict="unknown", reason="image_binding_missing")
        verdicts = {name: row.get("verdict", "unknown") if isinstance(row, dict) and row.get("verdict") in VERDICTS else "unknown" for name, row in evidence.items()}
        distinct = set(verdicts.values())
        conflict = distinct == {"pass", "fail"}
        verdict = "unknown" if conflict else "pass" if distinct == {"pass"} else "fail" if "fail" in distinct else "unknown"
        reason = "explicit_prediction_conflict" if conflict else "missing_or_unknown_prediction" if verdict == "unknown" else "explicit_failure_evidence" if verdict == "fail" else "both_predictions_pass"
        rows.append({**requirement, "verdict": verdict, "verdict_kind": "uncalibrated_prediction", "reason": reason, "conflict": conflict, "conflict_reason": "A and B disagree pass versus fail" if conflict else None, "observed_failures": [name for name, value in verdicts.items() if value == "fail"], "branch_verdicts": verdicts, "branch_evidence": evidence})
    rows = _dependent_rows(requirements, rows)
    source_image = report_a.get("image_binding", {}).get("source_sha256") if report_a else None
    rules = _source_rules(runner_evidence, source_image, prior_reports=[reports["A"]])
    serialized_evidence = asdict(runner_evidence) if runner_evidence else reports["A"].get("runner_evidence")
    retained = []
    if reports["A"].get("schema") == SCHEMA and reports["A"].get("method") == "A":
        retained = [item for item in [reports["A"].get("runner_evidence"), *reports["A"].get("retained_runner_evidence", [])] if isinstance(item, dict) and any(item.get(key) is False for key in ("source", "alpha"))]
    return {"schema": SCHEMA, "method": "C", "contract_hash": contract_hash, "requirements": rows, "source_rules": rules, "runner_evidence": deepcopy(serialized_evidence), "retained_runner_evidence": deepcopy(retained), "source_image_sha256": source_image or (runner_evidence.image_sha256 if runner_evidence else None), "verdict": _prediction_verdict(rows, rules), "verdict_kind": "uncalibrated_prediction", "accepted": False, "asset_accepted": False, "reports": deepcopy(reports)}


def legacy_visual_candidate_score(image_path: Path, alpha_metadata: dict[str, Any], scene_dna: dict[str, Any]) -> dict[str, Any]:
    """Execute the historical function with only its original alpha threshold."""
    from sage.server.trellis2_flux_bridge_server import Trellis2BridgeRuntime

    runtime = Trellis2BridgeRuntime(SimpleNamespace(alpha_bbox_threshold=24))
    return runtime._scene_dna_visual_candidate_score(image_path, alpha_metadata, scene_dna)


def select_candidate(rows: list[dict[str, Any]], method: str, *, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rank predictions for a provisional 3D follow-up, retaining all failures.

    Rows: candidate_id, reports={A:..., B:..., C:...}, runner_evidence (typed
    RunnerEvidence or None), legacy_style (the old helper's scalar score).
    Formal runners must pass contract, the canonical ID/hard/dependency source.
    B uses no A score: optional verified runner style-pair rank, then legacy/id.
    baseline uses only the unchanged legacy score after deterministic exclusion.
    """
    if method not in {"A", "B", "C", "baseline"}:
        raise ValueError("method must be A, B, C or baseline")
    candidates, eligible, seen = [], [], set()
    canonical = validate_contract(contract) if contract is not None else None
    templates = {item["id"]: deepcopy(item) for item in canonical or []}
    if canonical is None:
        templates = {item["id"]: deepcopy(item) for candidate in rows for branch in candidate.get("reports", {}).values() for item in branch.get("requirements", []) if isinstance(item, dict) and isinstance(item.get("id"), str)}
    expected_ids = set(templates)
    styles = {}
    if method == "B":
        for candidate in rows:
            style = candidate.get("style_pair_rank")
            if style is None:
                continue
            if not isinstance(style, dict) or style.get("schema") != "scene-v2-p020-runner-style-rank/v1" or type(style.get("rank")) is not int or style["rank"] not in {0, 1} or style.get("order_swap_checked") is not True or not isinstance(style.get("comparison_id"), str) or not style["comparison_id"] or not isinstance(style.get("candidate_ids"), list) or len(set(style["candidate_ids"])) != 2 or candidate.get("candidate_id") not in style["candidate_ids"]:
                raise ValueError("style_pair_rank requires a verified two-candidate runner comparison")
            styles[candidate["candidate_id"]] = deepcopy(style)
        if styles:
            if len(styles) != 2 or {style["rank"] for style in styles.values()} != {0, 1} or len({style["comparison_id"] for style in styles.values()}) != 1 or any(set(style["candidate_ids"]) != set(styles) for style in styles.values()):
                raise ValueError("style_pair_rank must describe one complete order-checked top-two pair")
    for candidate in rows:
        key = candidate.get("candidate_id")
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("candidate_id must be a unique nonempty string")
        seen.add(key)
        reports = candidate.get("reports", {})
        report = reports.get(method, {})
        if contract is not None:
            for branch in reports.values():
                if branch.get("contract_hash") and branch["contract_hash"] != content_hash(contract):
                    raise ValueError("selection report contract hash mismatch")
        evidence = candidate.get("runner_evidence")
        rules = _source_rules(evidence, prior_reports=list(reports.values()))
        hard_failures = [rule["id"] for rule in rules if rule["verdict"] == "fail"]
        selected_rows = [deepcopy(item) for item in report.get("requirements", []) if canonical is None or item.get("id") in expected_ids]
        for item in selected_rows:
            if canonical is not None:
                item.update(hard=templates[item["id"]]["hard"], depends_on=templates[item["id"]]["depends_on"])
        observed_ids = {item["id"] for item in selected_rows}
        if method != "baseline":
            selected_rows.extend({**templates[key], "id": key, "verdict": "unknown", "reason": "missing_method_requirement"} for key in sorted(expected_ids - observed_ids))
            if not selected_rows:
                selected_rows.append({"id": "missing_method_report", "verdict": "unknown", "reason": "missing_method_report"})
            if canonical is not None:
                selected_rows = _dependent_rows(canonical, selected_rows)
        hard_items = [item for item in selected_rows if item.get("hard", True)]
        blocked_items = [item for item in hard_items if item.get("blocked_by") or item.get("reason") == "blocked_unknown"]
        unblocked_items = [item for item in hard_items if not item.get("blocked_by") and item.get("reason") != "blocked_unknown"]
        fail_count = sum(item.get("verdict") == "fail" for item in unblocked_items)
        pass_count = sum(item.get("verdict") == "pass" for item in unblocked_items)
        # Blocking suppresses duplicate failure attribution, never the missing
        # observations. Otherwise an unknown root can erase an entire contract
        # from the denominator and beat candidates with much better coverage.
        hard_unknown_count = len(blocked_items) + sum(item.get("verdict") not in {"pass", "fail"} for item in unblocked_items)
        source_unknown_count = sum(rule["verdict"] == "unknown" for rule in rules)
        unknown_count = hard_unknown_count + source_unknown_count
        coverage = {"hard_requirement_count": len(hard_items), "observed_hard_requirement_count": pass_count + fail_count, "passed_hard_requirement_count": pass_count, "unknown_hard_requirement_count": hard_unknown_count, "blocked_hard_requirement_count": len(blocked_items), "observed_hard_fraction": (pass_count + fail_count) / len(hard_items) if hard_items else 0.0}
        atomic_soft = []
        atomic_ids = set()
        for item in reports.get("A", {}).get("requirements", []):
            atomic_ids.add(item.get("id"))
            value = item.get("contrast_score")
            atomic_soft.append(float(value) if type(value) in (int, float) and math.isfinite(float(value)) and 0 <= value <= 1 else 0.0)
        atomic_soft.extend(0.0 for _ in expected_ids - atomic_ids)
        weakest = min(atomic_soft, default=0.0)
        soft_policy = "minimum_all_raw_atomic_contrasts_including_blocked; missing_or_invalid=0"
        legacy = float(candidate.get("legacy_style", 0.0))
        if not math.isfinite(legacy):
            raise ValueError("legacy_style must be finite")
        if key in styles and (fail_count or unknown_count or hard_failures):
            raise ValueError("runner style comparison only applies after all hard predictions and source rules pass")
        style_rank = styles.get(key, {}).get("rank", 2) if styles else None
        if method == "baseline":
            rank = (-legacy, key)
        elif method == "B":
            rank = (fail_count, unknown_count, style_rank, -legacy, key) if styles else (fail_count, unknown_count, -legacy, key)
        else:
            rank = (fail_count, unknown_count, -weakest, -legacy, key)
        exact_inputs = {"hard_predicted_fail_count": fail_count, "hard_unknown_count": unknown_count, "requirement_unknown_count": hard_unknown_count, "source_rule_unknown_count": source_unknown_count, "weakest_atomic_contrast_score": weakest if method in {"A", "C"} else None, "atomic_soft_aggregation": soft_policy if method in {"A", "C"} else None, "style_pair_rank": style_rank if method == "B" else None, "legacy_style": legacy, "candidate_id": key}
        record = {"candidate_id": key, "reports": deepcopy(reports), "source_rules": rules, "runner_evidence": asdict(evidence) if evidence else None, "source_hard_failures": hard_failures, "source_hard_fail": bool(hard_failures), "selection_requirements": selected_rows, "predicted_fail_count": fail_count, "unknown_count": unknown_count, "coverage": coverage, "weakest_atomic_contrast_score": weakest, "atomic_soft_aggregation": soft_policy, "legacy_style": legacy, "style_pair_rank": styles.get(key), "exact_rank_inputs": exact_inputs, "rank_key": list(rank), "status": "reject_source" if hard_failures else "unselected", "asset_accepted": False}
        candidates.append(record)
        if not hard_failures:
            eligible.append((rank, record))
    if styles:
        all_hard_pass = [row for _, row in eligible if row["predicted_fail_count"] == 0 and row["unknown_count"] == 0]
        top_two = sorted(all_hard_pass, key=lambda row: (-row["legacy_style"], row["candidate_id"]))[:2]
        if {row["candidate_id"] for row in top_two} != set(styles):
            raise ValueError("style comparison must use the legacy-ranked top two hard-pass B candidates")
    chosen = min(eligible, key=lambda pair: pair[0])[1] if eligible else None
    if chosen:
        chosen["status"] = "provisional_for_3d"
    return {"schema": SCHEMA, "method": method, "contract_hash": content_hash(contract) if contract is not None else None, "canonical_contract_provided": contract is not None, "selected": chosen["candidate_id"] if chosen else None, "status": "provisional_for_3d" if chosen else "reject_batch", "asset_accepted": False, "failure_denominator": len(candidates), "source_hard_fail_count": sum(row["source_hard_fail"] for row in candidates), "candidates": candidates, "ranked_eligible_ids": [row["candidate_id"] for _, row in sorted(eligible, key=lambda pair: pair[0])]}
