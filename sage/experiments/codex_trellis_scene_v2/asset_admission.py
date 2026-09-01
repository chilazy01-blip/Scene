"""Missing-asset admission, lifecycle, and curated-library contracts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .capabilities import validate_asset_capability
from .content_chain import content_hash, file_binding, make_artifact_certificate


COUNT_CONTRACT_SCHEMA = "scene-v2-asset-count-contract/v1"
COUNT_EVIDENCE_SCHEMA = "scene-v2-asset-count-evidence/v1"
SUBFLOW_CONTRACT_SCHEMA = "scene-v2-missing-asset-subflow/v1"
ADMISSION_SCHEMA = "scene-v2-temporary-asset-admission/v1"
LIFECYCLE_SCHEMA = "scene-v2-asset-lifecycle/v1"

LIFECYCLE_STATES = (
    "generated_for_run",
    "scene_specific_approved",
    "candidate_for_curation",
    "curated",
    "rejected",
    "deprecated",
)

LEGAL_TRANSITIONS = {
    "generated_for_run": {"scene_specific_approved", "rejected", "deprecated"},
    "scene_specific_approved": {
        "candidate_for_curation",
        "rejected",
        "deprecated",
    },
    "candidate_for_curation": {"curated", "rejected", "deprecated"},
    "curated": {"deprecated"},
    "rejected": {"deprecated"},
    "deprecated": set(),
}

REQUIRED_ADMISSION_GATES = (
    "asset_contract",
    "candidate_2d_alpha",
    "candidate_2d_semantic",
    "candidate_2d_count",
    "trellis_generation",
    "multiview",
    "multiview_count",
    "dimensions",
    "canonical_front",
    "topology",
    "capability",
)


def build_count_contract(
    *,
    component_category: str,
    expected_count: int,
    arrangement: str = "single_row",
) -> dict[str, Any]:
    if not str(component_category).strip():
        raise ValueError("component_category must be non-empty")
    if int(expected_count) < 1:
        raise ValueError("expected_count must be positive")
    contract = {
        "schema": COUNT_CONTRACT_SCHEMA,
        "component_category": str(component_category),
        "expected_count": int(expected_count),
        "count_mode": "exactly",
        "arrangement": str(arrangement),
        "required_view_roles": ["front", "back", "left_side", "right_side"],
        "front_back_same_group_required": True,
        "maximum_side_depth_layers": 1,
        "second_row_forbidden": True,
    }
    contract["contract_hash"] = content_hash(contract)
    return contract


def build_missing_asset_subflow_contract(
    generation_spec: dict[str, Any], generation_contract: dict[str, Any]
) -> dict[str, Any]:
    contract = {
        "schema": SUBFLOW_CONTRACT_SCHEMA,
        "generation_spec_hash": content_hash(generation_spec),
        "generation_contract_hash": content_hash(generation_contract),
        "count_contract": deepcopy(generation_spec.get("count_contract")),
        "ordered_stages": [
            "asset_contract",
            "candidate_2d_generation",
            "candidate_2d_alpha_semantic_count_qa",
            "trellis_generation",
            "four_view_render_and_consistency_qa",
            "dimension_front_topology_capability_qa",
            "temporary_scene_admission",
            "explicit_lifecycle_transition",
        ],
        "assembly_requires": "scene_specific_approved",
        "curation_requires_explicit_independent_review": True,
        "single_scene_success_auto_curates": False,
    }
    contract["contract_hash"] = content_hash(contract)
    return contract


def _valid_binding(binding: Any) -> bool:
    if not isinstance(binding, dict):
        return False
    digest = str(binding.get("sha256") or "")
    return (
        int(binding.get("bytes", 0) or 0) > 0
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def validate_count_evidence(
    contract: dict[str, Any] | None, evidence: dict[str, Any] | None
) -> dict[str, Any]:
    if not isinstance(contract, dict):
        return {"ok": True, "required": False, "failures": []}
    failures: list[str] = []
    evidence = evidence if isinstance(evidence, dict) else {}
    if contract.get("schema") != COUNT_CONTRACT_SCHEMA:
        failures.append("count_contract_schema")
    expected_hash = content_hash(
        {key: value for key, value in contract.items() if key != "contract_hash"}
    )
    if contract.get("contract_hash") != expected_hash:
        failures.append("count_contract_hash")
    if evidence.get("schema") != COUNT_EVIDENCE_SCHEMA:
        failures.append("count_evidence_schema")
    if evidence.get("count_contract_hash") != contract.get("contract_hash"):
        failures.append("count_evidence_contract_hash")
    if str(evidence.get("review_method") or "") not in {
        "human_visual_review",
        "calibrated_instance_segmentation",
    }:
        failures.append("count_review_method")
    if not str(evidence.get("reviewer_id") or ""):
        failures.append("count_reviewer_id")
    views = evidence.get("views")
    views = views if isinstance(views, dict) else {}
    required_roles = list(contract.get("required_view_roles", []))
    expected_count = int(contract.get("expected_count", 0) or 0)
    for role in required_roles:
        row = views.get(role)
        if not isinstance(row, dict):
            failures.append(f"count_view_missing:{role}")
            continue
        if not _valid_binding(row.get("image")):
            failures.append(f"count_view_binding:{role}")
    front = views.get("front") if isinstance(views.get("front"), dict) else {}
    back = views.get("back") if isinstance(views.get("back"), dict) else {}
    for role, row in (("front", front), ("back", back)):
        if int(row.get("observed_count", -1)) != expected_count:
            failures.append(f"exact_count:{role}")
        signatures = row.get("member_signatures")
        signatures = signatures if isinstance(signatures, list) else []
        if len(signatures) != expected_count or len(set(signatures)) != expected_count:
            failures.append(f"member_signatures:{role}")
    if contract.get("front_back_same_group_required") and set(
        front.get("member_signatures", [])
    ) != set(back.get("member_signatures", [])):
        failures.append("front_back_group_mismatch")
    maximum_layers = int(contract.get("maximum_side_depth_layers", 1) or 1)
    for role in ("left_side", "right_side"):
        row = views.get(role) if isinstance(views.get(role), dict) else {}
        if int(row.get("observed_depth_layers", -1)) > maximum_layers:
            failures.append(f"side_depth_layers:{role}")
        if contract.get("second_row_forbidden") and row.get(
            "second_row_detected"
        ) is not False:
            failures.append(f"second_row:{role}")
    return {
        "ok": not failures,
        "required": True,
        "expected_count": expected_count,
        "failures": failures,
        "evidence_hash": content_hash(evidence),
    }


def _generation_contract_ok(contract: Any) -> bool:
    if not isinstance(contract, dict):
        return False
    if contract.get("schema") != "scene-v2-generation-contract/v1":
        return False
    expected = content_hash(
        {key: value for key, value in contract.items() if key != "content_key"}
    )
    return str(contract.get("content_key") or "") == expected


def evaluate_temporary_admission(
    asset_path: Path,
    *,
    generation_spec: dict[str, Any],
    generation_contract: dict[str, Any],
    candidate_2d_qa: dict[str, Any],
    trellis_generation: dict[str, Any],
    multiview_qa: dict[str, Any],
    dimension_qa: dict[str, Any],
    orientation_qa: dict[str, Any],
    topology_qa: dict[str, Any],
    capability: dict[str, Any],
    count_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not asset_path.is_file():
        raise FileNotFoundError(asset_path)
    count = validate_count_evidence(
        generation_spec.get("count_contract"), count_evidence
    )
    canonical_front = orientation_qa.get("canonical_front")
    canonical_front = canonical_front if isinstance(canonical_front, dict) else {}
    capability_validation = validate_asset_capability(capability)
    candidate_count = candidate_2d_qa.get("count")
    candidate_count = candidate_count if isinstance(candidate_count, dict) else {}
    expected_count = int(
        generation_spec.get("count_contract", {}).get("expected_count", 0) or 0
    )
    gates = {
        "asset_contract": _generation_contract_ok(generation_contract),
        "candidate_2d_alpha": bool(
            candidate_2d_qa.get("alpha", {}).get("ok")
        ),
        "candidate_2d_semantic": bool(
            candidate_2d_qa.get("semantic", {}).get("ok")
        ),
        "candidate_2d_count": bool(
            not count["required"]
            or (
                candidate_count.get("ok")
                and int(candidate_count.get("observed_count", -1))
                == expected_count
                and _valid_binding(candidate_count.get("image"))
            )
        ),
        "trellis_generation": bool(
            trellis_generation.get("ok")
            and str(trellis_generation.get("job_id") or "")
        ),
        "multiview": bool(
            multiview_qa.get("evaluated")
            and int(multiview_qa.get("rendered_view_count", 0) or 0) == 4
            and not multiview_qa.get("missing_views")
            and multiview_qa.get("hard_geometry_gate_passed")
            and (
                multiview_qa.get("automated_pixel_multiview_pass")
                or multiview_qa.get("independent_human_review", {}).get(
                    "accepted"
                )
            )
        ),
        "multiview_count": bool(count["ok"]),
        "dimensions": bool(
            dimension_qa.get("accepted")
            and dimension_qa.get("measured_from_glb") is True
        ),
        "canonical_front": bool(
            orientation_qa.get("accepted")
            and canonical_front.get("axis") in {"+x", "-x", "+y", "-y"}
            and float(canonical_front.get("confidence", 0.0) or 0.0) >= 0.7
        ),
        "topology": bool(
            topology_qa.get("trimesh_load_ok")
            and topology_qa.get("finite_bounds")
            and int(topology_qa.get("face_count", 0) or 0) > 0
            and topology_qa.get("cleanup_accepted")
        ),
        "capability": bool(capability_validation["ok"]),
    }
    failures = [name for name in REQUIRED_ADMISSION_GATES if not gates[name]]
    subflow = build_missing_asset_subflow_contract(
        generation_spec, generation_contract
    )
    upstream = {
        "subflow_contract_hash": subflow["contract_hash"],
        "generation_spec_hash": content_hash(generation_spec),
        "generation_contract_hash": content_hash(generation_contract),
        "candidate_2d_qa_hash": content_hash(candidate_2d_qa),
        "trellis_generation_hash": content_hash(trellis_generation),
        "multiview_qa_hash": content_hash(multiview_qa),
        "dimension_qa_hash": content_hash(dimension_qa),
        "orientation_qa_hash": content_hash(orientation_qa),
        "topology_qa_hash": content_hash(topology_qa),
        "capability_hash": content_hash(capability),
        "count_evidence_hash": content_hash(count_evidence),
    }
    certificate = make_artifact_certificate(
        asset_path,
        upstream=upstream,
        rules={"kind": "temporary_scene_asset_admission", "version": 1},
    )
    return {
        "schema": ADMISSION_SCHEMA,
        "asset": {"path": str(asset_path.resolve()), **file_binding(asset_path)},
        "subflow_contract": subflow,
        "gates": gates,
        "count_validation": count,
        "capability_validation": capability_validation,
        "accepted": not failures,
        "failures": failures,
        "lifecycle_status": (
            "scene_specific_approved" if not failures else "generated_for_run"
        ),
        "content_certificate": certificate,
        "admission_hash": content_hash(certificate),
        "auto_curated": False,
    }


def new_lifecycle_record(
    asset_id: str, admission: dict[str, Any]
) -> dict[str, Any]:
    status = str(admission.get("lifecycle_status") or "generated_for_run")
    if status not in {"generated_for_run", "scene_specific_approved"}:
        raise ValueError("admission has invalid initial lifecycle status")
    return {
        "schema": LIFECYCLE_SCHEMA,
        "asset_id": str(asset_id),
        "status": status,
        "admission_hash": str(admission.get("admission_hash") or ""),
        "history": [
            {
                "from": None,
                "to": status,
                "evidence_hash": str(admission.get("admission_hash") or ""),
            }
        ],
    }


def transition_lifecycle(
    record: dict[str, Any],
    target_status: str,
    *,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    current = str(record.get("status") or "")
    if current not in LIFECYCLE_STATES or target_status not in LIFECYCLE_STATES:
        raise ValueError("unknown asset lifecycle status")
    if target_status not in LEGAL_TRANSITIONS[current]:
        raise ValueError(f"illegal asset lifecycle transition: {current}->{target_status}")
    if target_status == "candidate_for_curation" and not evidence.get(
        "scene_independent_review_requested"
    ):
        raise ValueError("curation candidacy requires an explicit independent review")
    if target_status == "curated":
        if not evidence.get("independent_review_accepted"):
            raise ValueError("curation requires accepted independent review")
        if not str(evidence.get("license_id") or ""):
            raise ValueError("curation requires license metadata")
        if not str(evidence.get("qa_hash") or ""):
            raise ValueError("curation requires QA hash")
    updated = deepcopy(record)
    updated["status"] = target_status
    updated.setdefault("history", []).append(
        {
            "from": current,
            "to": target_status,
            "evidence_hash": content_hash(evidence),
        }
    )
    return updated


def audit_library_coverage(
    entries: list[dict[str, Any]], high_frequency_categories: list[str]
) -> dict[str, Any]:
    rows = []
    required_metadata = (
        "canonical_front",
        "handedness",
        "dimension_policy",
        "capability",
        "license",
        "asset_sha256",
        "qa_hash",
        "known_failure_scenarios",
    )
    for category in high_frequency_categories:
        assets = [
            row
            for row in entries
            if row.get("category") == category
            and row.get("lifecycle_status") == "curated"
            and row.get("qa_status") == "approved"
        ]
        style_signatures = {
            str(row.get("style_signature") or "") for row in assets
        } - {""}
        content_hashes = {
            str(row.get("asset_sha256") or "") for row in assets
        } - {""}
        incomplete = [
            str(row.get("asset_id") or "")
            for row in assets
            if any(key not in row or row.get(key) in (None, "") for key in required_metadata)
        ]
        rows.append(
            {
                "category": category,
                "approved_asset_count": len(assets),
                "style_signature_count": len(style_signatures),
                "unique_content_count": len(content_hashes),
                "incomplete_asset_ids": incomplete,
                "passes": (
                    len(assets) >= 3
                    and len(content_hashes) >= 3
                    and len(style_signatures) >= 2
                    and not incomplete
                ),
            }
        )
    return {
        "schema": "scene-v2-curated-library-coverage/v1",
        "minimum_assets_per_category": 3,
        "minimum_style_signatures_per_category": 2,
        "categories": rows,
        "ok": bool(rows) and all(row["passes"] for row in rows),
    }
