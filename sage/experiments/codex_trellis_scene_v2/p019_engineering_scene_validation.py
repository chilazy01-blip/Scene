"""P019 provider/scene integration with a separate, explicit sofa request.

This does not accept the original full furniture specification or contribute
to its benchmark pass rate. Original wood-appearance unknowns and surface
defects remain bound evidence. No original review, audit, or strict harness is
modified, and no furnishing geometry or texture is created or edited.

From the scene repository::

    python -m sage.experiments.codex_trellis_scene_v2.p019_engineering_scene_validation freeze

Inspect each selected packet's images against the NEW requirements. Complete
its review template and save to asset_reviews/<case_id>.json, then::

    python -m sage.experiments.codex_trellis_scene_v2.p019_engineering_scene_validation prepare
    # Only after the caller's P007 scheduling/admission:
    python -m sage.experiments.codex_trellis_scene_v2.p019_engineering_scene_validation run
    python -m sage.experiments.codex_trellis_scene_v2.p019_engineering_scene_validation verify

All outputs are isolated in <root>/engineering_scene_validation. Final scene
review templates are emitted after rendering. CPU preparation, original visual
judgments, and an unfilled template never count as completed scene acceptance.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
from typing import Any

from . import p019_scene_validation as core
from .asset_admission import new_lifecycle_record
from .asset_source_policy import audit_asset_source_policy
from .content_chain import content_hash, file_binding, make_artifact_certificate, verify_artifact_certificate
from .p019_provider_benchmark import DEFAULT_ROOT, PROVIDERS, candidate_quality, read_json, write_json
from .resource_health import append_health_checkpoint
from .runtime import assemble_with_blender
from .scene_graph import build_typed_scene_graph, materialize_scene_graph
from .scene_render_acceptance import evaluate_scene_render_manifest, render_and_evaluate_scene
from .validator import validate_layout


SCHEMA = "p019-engineering-scene-validation/v1"
SCOPE = "provider_route_and_scene_integration_only"
SCOPE_FIELDS = {"scope": SCOPE, "original_full_specification_passed": False, "count_toward_original_benchmark": False, "auto_curated": False}
SUPPORT_INTERPRETATION = "Visually distinct dark feet with open clearance below the sofa body. Narrow side support rails above the foot tips are recorded, not interpreted as separate mesh components or a floor-reaching closed plinth."
REQUIREMENTS = (
    ("one_sofa", "One coherent two-seat sofa", "observations", "one sofa"),
    ("two_seat_cushions", "Exactly two seat cushions", "observations", "two seat cushions"),
    ("two_back_cushions", "Exactly two back cushions", "observations", "two back cushions"),
    ("two_armrests", "Exactly two armrests", "observations", "two armrests"),
    ("beige_fabric_appearance", "Beige fabric upholstery appearance", "supplementary_observations", "beige fabric appearance"),
    ("dark_leg_color", "Dark leg appearance", "supplementary_observations", "dark leg color"),
    ("distinct_legs_open_clearance", "Visually distinct legs and open clearance beneath the sofa", "observations", "separate legs and open underside"),
)
GEOMETRY_FACTS = (
    ("observations", "coherent lower body and bottom panel without clearance-blocking geometry"),
    ("observations", "no obvious floating parts, gross interpenetration, missing surfaces, or incorrectly sealed openings"),
    ("observations", "no obvious unrelated or extra geometry"),
    ("supplementary_observations", "absence of newly exposed major geometry defects"),
)
require, bound, check_binding = core.require, core.bound, core.check_binding


def check_scope(document: dict[str, Any]) -> None:
    for key, value in SCOPE_FIELDS.items():
        require(document.get(key) == value and type(document.get(key)) is type(value), f"engineering scope violation: {key}")


def check_fact(visual: dict[str, Any], stage: str, requirement: str) -> dict[str, Any]:
    matches = [row for row in visual.get(stage, {}).get("checks", []) if row.get("requirement") == requirement]
    require(len(matches) == 1 and matches[0].get("status") == "pass", f"prior requirement not explicitly passed: {stage}:{requirement}")
    require(matches[0].get("observation") and matches[0].get("evidence_views"), f"prior requirement evidence missing: {requirement}")
    return deepcopy(matches[0])


def check_sha_record(record: dict[str, Any]) -> Path:
    path = Path(record["path"])
    require(file_binding(path)["sha256"] == record.get("sha256"), f"review image changed: {path}")
    if "bytes" in record:
        check_binding(record)
    return path


def verify_engineering_source(root: Path, frozen: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Revalidate generation and all view evidence without changing strict QA.

    This intentionally does not call or override core.verify_audit: that method
    requires full ORIGINAL specification acceptance. Here a separately frozen
    engineering request plus a new per-requirement review is mandatory.
    """
    require(case.get("category") == "sofa" and case.get("provider") in PROVIDERS, "engineering route only admits frozen sofa cases")
    require(case in frozen["cases"], "case is absent from original frozen benchmark")
    directory = root / "cases" / case["id"]
    audit = read_json(directory / "audit.json")
    require(audit.get("schema") == "p019-case-audit/v1" and audit.get("case_id") == case["id"] and audit.get("provider") == case["provider"], "original audit identity mismatch")
    for name in ("automated_accepted", "source_policy_ok", "glb_ok", "hard_geometry_gate_passed", "frozen_three_d_control_passed"):
        require(audit.get(name) is True, f"original automated gate failed: {name}")
    generation = read_json(directory / "generation.json")
    contract = read_json(directory / "generation_contract.json")
    core.sealed_key(contract)
    require(contract == generation.get("generation_contract") and contract["content_key"] == audit.get("generation_key") == generation.get("generation_key"), "generation contract/key mismatch")
    require(contract.get("schema") == "scene-v2-generation-contract/v1" and contract.get("case_id") == case["id"] and contract.get("frozen_cases_key") == frozen["content_key"], "generation contract case/schema mismatch")
    require(contract.get("target_dimensions_m") == case["dimensions"] and contract.get("image_provider") == case["provider"], "generation specification/provider mismatch")
    for key in ("prompt", "model_fingerprint", "rmbg_fingerprint", "code_version", "candidate_job_id", "trellis_job_id", "candidate_evidence_manifest"):
        require(contract.get(key), f"incomplete generation contract: {key}")
    require(contract.get("pipeline") == {"type": "512", "steps": 12, "texture_size": 512, "decimation_target": 300000, "preprocess_image": True}, "frozen reconstruction control mismatch")
    glb = Path(audit["glb_path"])
    result = read_json(directory / "trellis" / "result.json")
    require(result.get("ok") is True and result.get("status") == "generated", "TRELLIS did not complete")
    require(file_binding(glb) == result.get("glb_binding") and file_binding(glb)["sha256"] == audit.get("glb_sha256"), "reviewed GLB changed")
    metadata = read_json(directory / "trellis" / "bridge_metadata.json")
    require(metadata == generation.get("bridge_metadata") and content_hash(metadata) == contract.get("bridge_metadata_hash"), "bridge metadata changed")
    require(metadata.get("job_id") == contract.get("trellis_job_id") == result.get("job_id") == generation.get("job_id"), "TRELLIS job mismatch")
    request = read_json(directory / "trellis" / "request.json")
    require(content_hash(request["payload"]) == request.get("request_hash") == contract.get("generation_request_hash") and request["payload"] == generation.get("request"), "generation request mismatch")
    candidate = read_json(directory / "candidate" / "bridge_metadata.json")
    quality = candidate_quality(candidate, case, contract["candidate_job_id"])
    require(quality["ok"], f"candidate source rejected: {quality.get('failures')}")
    require(file_binding(Path(quality["source_rgb"]["path"])) == contract.get("reference_image"), "original reference hash changed")
    source = audit_asset_source_policy({"mode": "generate", "results": [{"object_id": case["id"], "category": case["category"], "status": "generated", "metadata": generation}]})
    require(source["ok"], f"generated source gate failed: {source.get('failures')}")
    require(set(audit["standard_views"]) == set(core.VIEW_AXES) and set(audit["low_under_views"]) == set(core.LOW_UNDER_AXES), "required 4+8 asset views missing")
    evidence = {f"standard_{axis}": Path(path) for axis, path in audit["standard_views"].items()}
    evidence.update({f"low_under_{axis}": Path(path) for axis, path in audit["low_under_views"].items()})
    evidence.update(bridge_metadata=directory / "trellis" / "bridge_metadata.json", source_policy=directory / "source_policy_report.json", standard_report=Path(audit["standard_qa_path"]), low_under_report=Path(audit["low_under_qa_path"]))
    for name in ("standard_contact_sheet", "low_under_contact_sheet"):
        if audit.get(name):
            evidence[name] = Path(audit[name])
    certificate = read_json(directory / "audit_certificate.json")
    rules = certificate.get("rules", {})
    require(rules.get("schema") == "p019-asset-audit/v1" and rules.get("standard_axes") == list(core.VIEW_AXES) and rules.get("low_under_axes") == list(core.LOW_UNDER_AXES), "unexpected original capture rules")
    ok, reasons = verify_artifact_certificate(certificate, glb, upstream={"generation_contract": contract, "generation_key": contract["content_key"]}, rules=rules, evidence=evidence)
    require(ok, f"original GLB/view certificate changed: {reasons}")
    require(read_json(Path(audit["standard_qa_path"])).get("hard_geometry_gate_passed") is True and read_json(Path(audit["low_under_qa_path"])).get("ok") is True, "multiview hard geometry failure")

    visual = read_json(directory / "visual_review.json")
    require(visual.get("reviewer") and visual.get("glb_sha256") == audit["glb_sha256"] and visual.get("generation_key") == contract["content_key"], "original visual review GLB binding mismatch")
    require(visual.get("requirement_compliance_passed") is False, "this separate route preserves an unsuccessful original full specification")
    require(visual.get("geometry_multiview_passed") is True, "original visual geometry did not pass")
    original_judgment = Path(visual["blind_review_path"])
    supplement_judgment = Path(visual["supplementary_review_path"])
    require(read_json(original_judgment) == visual["observations"] and read_json(supplement_judgment) == visual["supplementary_observations"], "original judgment documents differ")
    for stage in ("observations", "supplementary_observations"):
        require(visual[stage].get("geometry_multiview_passed") is True and visual[stage].get("reviewer") and not visual[stage].get("major_issues"), f"original {stage} geometry/major issues failure")
    original_request = original_judgment.parent / "review_request.json"
    blind = read_json(original_request)
    rendered_views = {f"standard_views:{axis}": Path(path) for axis, path in audit["standard_views"].items()}
    rendered_views.update({f"low_under_views:{axis}": Path(path) for axis, path in audit["low_under_views"].items()})
    require(set(blind["views"]) == set(rendered_views) == set(visual["observations"]["reviewed_views"]), "original visual review did not inspect all 4+8 views")
    for name, expected in rendered_views.items():
        require(file_binding(check_sha_record(blind["views"][name])) == file_binding(expected), f"blind image not from reviewed GLB: {name}")
    supplement_binding_path = directory / "supplementary_1400px" / "binding.json"
    supplement = read_json(supplement_binding_path)
    require(supplement.get("case_id") == case["id"] and supplement.get("generation_key") == contract["content_key"] and check_binding(supplement["glb"]).resolve() == glb.resolve(), "supplement GLB binding mismatch")
    require(supplement.get("resolution") == 1400 and set(supplement["views"]) == set(core.VIEW_AXES), "supplementary four-view capture missing")
    supplement_request = original_judgment.parent / "supplement_1400px" / "request.json"
    supplementary_blind = read_json(supplement_request)
    for axis, record in supplement["views"].items():
        expected = check_binding(record)
        require(file_binding(check_sha_record(supplementary_blind["views"][axis])) == file_binding(expected), "supplementary blind image differs")
        rendered_views[f"supplement_1400px:{axis}"] = expected
    require(set(visual["supplementary_observations"]["reviewed_views"]) == {f"supplement_1400px:{axis}" for axis in core.VIEW_AXES}, "supplementary visual review missing views")
    facts = {identifier: check_fact(visual, stage, old_requirement) for identifier, _, stage, old_requirement in REQUIREMENTS}
    geometry_facts = [check_fact(visual, stage, requirement) for stage, requirement in GEOMETRY_FACTS]
    for fact in [*facts.values(), *geometry_facts]:
        require(set(fact["evidence_views"]) <= set(rendered_views), "original fact names unknown view")
    findings = [{"stage": stage, **deepcopy(row)} for stage in ("observations", "supplementary_observations") for row in visual[stage]["checks"] if row["status"] != "pass"]
    require(any(row["requirement"] == "dark wooden leg appearance" and row["status"] == "unknown" for row in findings), "original wood-appearance unknown was not preserved")
    evidence.update(audit=directory / "audit.json", audit_certificate=directory / "audit_certificate.json", original_visual_review=directory / "visual_review.json", original_judgment=original_judgment, supplement_judgment=supplement_judgment, original_review_request=original_request, supplement_review_request=supplement_request, supplement_binding=supplement_binding_path, generation=directory / "generation.json", generation_contract=directory / "generation_contract.json", asset_object=directory / "asset_object.json", candidate_metadata=directory / "candidate" / "bridge_metadata.json", trellis_request=directory / "trellis" / "request.json", trellis_result=directory / "trellis" / "result.json")
    evidence.update({f"reviewed_image/{name}": path for name, path in rendered_views.items()})
    return {**SCOPE_FIELDS, "case": deepcopy(case), "asset": bound(glb), "generation_key": contract["content_key"], "generation": generation, "source_policy": source,
            "prior_requirement_facts": facts, "prior_geometry_facts": geometry_facts, "original_quality_findings": findings,
            "original_uncertainties": {stage: visual[stage].get("uncertainties", []) for stage in ("observations", "supplementary_observations")},
            "views": {name: bound(path) for name, path in rendered_views.items()}, "evidence": {name: bound(path) for name, path in evidence.items()}}


def engineering_request() -> dict[str, Any]:
    request = {"schema": "p019-engineering-request/v1", **SCOPE_FIELDS,
               "prompt": "一个米色布艺双人沙发，两座垫、两靠垫、两扶手，深色且可独立辨认的脚，沙发底部与地面之间有开放空隙。",
               "requirements": [{"id": identifier, "text": text} for identifier, text, _, _ in REQUIREMENTS],
               "support_interpretation": SUPPORT_INTERPRETATION,
               "scene_requirements": ["one referenced sofa per provider scene", "floor supported", "inside the room", "complete in at least one actual rendered view"],
               "quality_scope": {"wooden_leg_appearance": "not_requested; original unknown remains recorded", "surface_finish_perfection": "not_requested; original observed blemishes remain recorded", "physical_material_identity": "not_evaluated"}}
    request["content_key"] = content_hash(request)
    return request


def asset_review_template(packet: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return {"schema": "p019-engineering-asset-review/v1", **SCOPE_FIELDS, "case_id": packet["case"]["id"], "reviewer": "", "review_mode": "explicit_engineering_requirement_recheck", "request_content_key": request["content_key"], "packet_content_key": packet["content_key"], "asset_glb_sha256": packet["asset"]["sha256"], "generation_key": packet["generation_key"],
            "support_interpretation": SUPPORT_INTERPRETATION, "acknowledged_original_quality_findings_hash": content_hash(packet["original_quality_findings"]), "reviewed_views": [],
            "checks": [{"requirement_id": identifier, "status": "unreviewed", "observation": "", "evidence_views": []} for identifier, _, _, _ in REQUIREMENTS]}


def verify_asset_review(review: dict[str, Any], packet: dict[str, Any], request: dict[str, Any]) -> None:
    check_scope(review)
    require(review.get("schema") == "p019-engineering-asset-review/v1" and review.get("reviewer") and review.get("review_mode") == "explicit_engineering_requirement_recheck", "a new explicit engineering review is required")
    for key, expected in (("case_id", packet["case"]["id"]), ("request_content_key", request["content_key"]), ("packet_content_key", packet["content_key"]), ("asset_glb_sha256", packet["asset"]["sha256"]), ("generation_key", packet["generation_key"]), ("support_interpretation", SUPPORT_INTERPRETATION), ("acknowledged_original_quality_findings_hash", content_hash(packet["original_quality_findings"]))):
        require(review.get(key) == expected, f"engineering review binding mismatch: {key}")
    require(set(review.get("reviewed_views", [])) == set(packet["views"]), "new review must inspect every bound standard/low/under/supplementary view")
    checks = review.get("checks", [])
    require(len(checks) == len(REQUIREMENTS) and {row.get("requirement_id") for row in checks} == {row[0] for row in REQUIREMENTS}, "new request checklist incomplete")
    for row in checks:
        require(row.get("status") == "pass" and str(row.get("observation") or "").strip(), f"new requirement not passed: {row['requirement_id']}")
        views = set(row.get("evidence_views", []))
        require(views and views <= set(packet["views"]) and views.intersection(packet["prior_requirement_facts"][row["requirement_id"]]["evidence_views"]), "new requirement evidence missing or unrelated")


def freeze(root: Path) -> dict[str, Any]:
    output = root / "engineering_scene_validation"
    existing = output / "engineering_frozen.json"
    if existing.is_file():
        return verify_frozen(root)
    original = read_json(root / "frozen_cases.json")
    core.sealed_key(original)
    require(content_hash(read_json(root / "frozen_plan.json")) == original["preregistration_hash"], "original preregistration changed")
    request = engineering_request()
    write_json(output / "scene_request.json", request)
    candidates, excluded = [], []
    for case in original["cases"]:
        if case["category"] != "sofa":
            excluded.append({"case_id": case["id"], "reason": "outside new sofa request"})
            continue
        try:
            candidates.append(verify_engineering_source(root, original, case))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            excluded.append({"case_id": case["id"], "reason": f"{type(exc).__name__}: {exc}"})
    selected = {}
    for row in sorted(candidates, key=lambda item: (item["case"]["replicate"], item["case"]["id"])):
        selected.setdefault(row["case"]["provider"], row)
    require(set(selected) == set(PROVIDERS), f"both providers need a source/geometry/fact-qualified sofa: {excluded}")
    packet_bindings = {}
    for provider, packet in selected.items():
        packet["request_content_key"] = request["content_key"]
        packet["content_key"] = content_hash(packet)
        identifier = packet["case"]["id"]
        packet_path = output / "review_packets" / f"{identifier}.json"
        write_json(packet_path, packet)
        write_json(output / "review_templates" / f"{identifier}.json", asset_review_template(packet, request))
        packet_bindings[provider] = bound(packet_path)
    frozen = {"schema": "p019-engineering-frozen/v1", **SCOPE_FIELDS, "request": bound(output / "scene_request.json"), "original_cases": bound(root / "frozen_cases.json"), "original_plan": bound(root / "frozen_plan.json"), "packets": packet_bindings, "excluded": excluded, "eligible_case_ids": [row["case"]["id"] for row in candidates], "selection_policy": "lowest original replicate per provider that passes generation/source/4+8 hard geometry and all explicitly required original facts; new engineering review still required"}
    frozen["content_key"] = content_hash(frozen)
    write_json(existing, frozen)
    return frozen


def verify_frozen(root: Path) -> dict[str, Any]:
    output = root / "engineering_scene_validation"
    frozen = read_json(output / "engineering_frozen.json")
    check_scope(frozen)
    core.sealed_key(frozen)
    require(frozen.get("schema") == "p019-engineering-frozen/v1" and set(frozen["packets"]) == set(PROVIDERS), "engineering freeze schema/coverage mismatch")
    request = read_json(check_binding(frozen["request"]))
    require(request == engineering_request(), "engineering requirements changed")
    original = read_json(check_binding(frozen["original_cases"]))
    check_binding(frozen["original_plan"])
    for provider, binding in frozen["packets"].items():
        packet = read_json(check_binding(binding))
        core.sealed_key(packet)
        check_scope(packet)
        require(packet["case"]["provider"] == provider and packet["request_content_key"] == request["content_key"], "engineering packet provider/request changed")
        current = verify_engineering_source(root, original, packet["case"])
        require(current == {key: value for key, value in packet.items() if key not in {"content_key", "request_content_key"}}, "source/quality findings changed since engineering freeze")
    return frozen


def prepare(root: Path) -> dict[str, Any]:
    output = root / "engineering_scene_validation"
    if (output / "engineering_prepared.json").is_file():
        return verify_prepared(root)
    frozen = verify_frozen(root)
    request = read_json(output / "scene_request.json")
    files = {"freeze": bound(output / "engineering_frozen.json"), "request": bound(output / "scene_request.json")}
    scenes = {}
    # Validate both new reviews before any asset is staged.
    packets = {provider: read_json(Path(binding["path"])) for provider, binding in frozen["packets"].items()}
    for packet in packets.values():
        review_path = output / "asset_reviews" / f"{packet['case']['id']}.json"
        verify_asset_review(read_json(review_path), packet, request)
        files[f"asset_review/{packet['case']['id']}"] = bound(review_path)
    for provider, packet in packets.items():
        row = deepcopy(packet)
        directory = output / provider
        asset_dir = directory / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        destination = asset_dir / f"{packet['case']['id']}.glb"
        shutil.copyfile(check_binding(packet["asset"]), destination)
        row["staged_asset"] = bound(destination)
        require(file_binding(destination) == file_binding(Path(packet["asset"]["path"])), "engineering staging changed GLB")
        plan = core.make_plan([row], provider)
        # Center the one sofa while retaining the audited orientation/dimensions.
        plan["objects"][0].update(x=plan["room"]["width"] / 2, y=3.25, provenance="p019_engineering_request")
        plan.update(SCOPE_FIELDS, scene_purpose=SCOPE, engineering_request_content_key=request["content_key"])
        plan["scene_graph"] = materialize_scene_graph(build_typed_scene_graph(plan), plan["objects"])
        layout_qa = validate_layout(plan)
        require(layout_qa["ok"], f"engineering layout failed: {layout_qa['violations']}")
        resolution = {**SCOPE_FIELDS, "mode": "generate", "asset_dir": str(asset_dir), "ready_for_assembly": True, "results": [{"object_id": row["case"]["id"], "category": "sofa", "status": "generated", "metadata": row["generation"], "lifecycle": new_lifecycle_record(row["case"]["id"], {"lifecycle_status": "generated_for_run", "admission_hash": files[f"asset_review/{row['case']['id']}"]["sha256"]})}]}
        source = audit_asset_source_policy(resolution)
        require(source["ok"], "engineering staging source gate failed")
        scene_request = {**deepcopy(request), "provider": provider, "asset_refs": [{"object_id": row["case"]["id"], "asset": row["asset"], "generation_key": row["generation_key"]}], "request_content_key": request["content_key"]}
        scene_request.pop("content_key")
        for name, value in (("scene_request", scene_request), ("layout_plan", plan), ("asset_references", {**SCOPE_FIELDS, "assets": [row]}), ("asset_resolution", resolution), ("asset_source_policy", {**source, **SCOPE_FIELDS}), ("layout_qa", {**layout_qa, **SCOPE_FIELDS})):
            path = directory / f"{name}.json"
            write_json(path, value)
            files[f"{provider}/{name}"] = bound(path)
        files[f"{provider}/staged_asset"] = row["staged_asset"]
        scenes[provider] = {"case_id": row["case"]["id"], "asset_glb_sha256": row["asset"]["sha256"], "original_quality_findings": row["original_quality_findings"]}
    prepared = {"schema": "p019-engineering-prepared/v1", **SCOPE_FIELDS, "status": "prepared_not_rendered", "engineering_frozen_key": frozen["content_key"], "files": files, "scenes": scenes}
    prepared["content_key"] = content_hash(prepared)
    write_json(output / "engineering_prepared.json", prepared)
    return prepared


def verify_prepared(root: Path) -> dict[str, Any]:
    output = root / "engineering_scene_validation"
    frozen = verify_frozen(root)
    request = read_json(output / "scene_request.json")
    prepared = read_json(output / "engineering_prepared.json")
    core.sealed_key(prepared)
    check_scope(prepared)
    require(prepared.get("schema") == "p019-engineering-prepared/v1" and prepared["engineering_frozen_key"] == frozen["content_key"] and set(prepared["scenes"]) == set(PROVIDERS), "engineering preparation binding/coverage mismatch")
    for binding in prepared["files"].values():
        check_binding(binding)
    for provider, binding in frozen["packets"].items():
        packet = read_json(Path(binding["path"]))
        verify_asset_review(read_json(output / "asset_reviews" / f"{packet['case']['id']}.json"), packet, request)
        rows = read_json(output / provider / "asset_references.json")["assets"]
        require(len(rows) == 1 and {key: value for key, value in rows[0].items() if key != "staged_asset"} == packet, "engineering asset reference differs from frozen packet")
        require(file_binding(check_binding(rows[0]["staged_asset"])) == file_binding(check_binding(packet["asset"])), "engineering GLB altered after preparation")
    return prepared


def scene_review_template(directory: Path, certificate: dict[str, Any], request_key: str) -> dict[str, Any]:
    return {"schema": "p019-engineering-scene-review/v1", **SCOPE_FIELDS, "reviewer": "", "scene_glb_sha256": file_binding(directory / "scene.glb")["sha256"], "content_certificate_hash": certificate["certificate_hash"], "request_content_key": request_key,
            "reviewed_rgb_images": [], "original_quality_findings_acknowledged": False,
            "checks": [{"requirement_id": identifier, "status": "unreviewed", "observation": ""} for identifier in ("correct_referenced_sofa", "requested_sofa_appearance", "floor_support_and_room_placement", "complete_visibility")]}


def run(root: Path, blender: Path, resolution: int, provider: str | None = None) -> dict[str, Any]:
    output = root / "engineering_scene_validation"
    prepared = verify_prepared(root)
    require(blender.is_file(), "Blender binary missing")
    for name in ([provider] if provider else PROVIDERS):
        directory = output / name
        if (directory / "engineering_scene_certificate.json").is_file():
            verify_scene(root, name)
            continue
        append_health_checkpoint(output / "resource_health.jsonl", stage=f"p019_engineering_assemble:{name}", require_healthy=True)
        scene = directory / "scene.glb"
        assembly = assemble_with_blender(directory / "layout_plan.json", directory / "assets", scene, blender_bin=blender, preview_image=directory / "scene_front_45.png", preview_image_center=directory / "scene_front_center_45.png")
        write_json(directory / "assembly_report.json", {**assembly, **SCOPE_FIELDS})
        plan = read_json(directory / "layout_plan.json")
        rows = read_json(directory / "asset_references.json")["assets"]
        geometry = core.inspect_scene(scene, plan, rows)
        write_json(directory / "geometry_qa.json", {**geometry, **SCOPE_FIELDS})
        append_health_checkpoint(output / "resource_health.jsonl", stage=f"p019_engineering_render:{name}", require_healthy=True)
        render = render_and_evaluate_scene(blender_bin=blender, scene_glb=scene, plan_path=directory / "layout_plan.json", asset_dir=directory / "assets", output_dir=directory / "renders", resolution=resolution)
        require(render.get("evaluated"), "real engineering scene rendering failed")
        write_json(directory / "renders" / "scene_render_acceptance_report.json", {**render, **SCOPE_FIELDS})
        verify_prepared(root)
        rules = {"schema": SCHEMA, **SCOPE_FIELDS, "resolution": resolution, "harness": bound(Path(__file__)), "shared_helpers": bound(Path(core.__file__)), "blender": bound(blender), "assembler": bound(Path(__file__).resolve().parents[2] / "scripts" / "blender_assemble_sage_scene.py"), "renderer": bound(Path(__file__).resolve().parents[2] / "scripts" / "blender_render_sage_diagnostics.py")}
        certificate = make_artifact_certificate(scene, upstream={"engineering_prepared_content_key": prepared["content_key"], "provider": name, **SCOPE_FIELDS}, rules=rules, evidence=core.scene_evidence(directory))
        write_json(directory / "engineering_scene_certificate.json", certificate)
        write_json(directory / "scene_review_template.json", scene_review_template(directory, certificate, read_json(output / "scene_request.json")["content_key"]))
    return verify(root)


def verify_scene(root: Path, provider: str) -> dict[str, Any]:
    output = root / "engineering_scene_validation"
    prepared = verify_prepared(root)
    directory = output / provider
    scene = directory / "scene.glb"
    certificate = read_json(directory / "engineering_scene_certificate.json")
    require(certificate["rules"].get("schema") == SCHEMA, "engineering scene certificate schema mismatch")
    check_scope(certificate["rules"])
    for key in ("harness", "shared_helpers", "blender", "assembler", "renderer"):
        check_binding(certificate["rules"][key])
    ok, reasons = verify_artifact_certificate(certificate, scene, upstream={"engineering_prepared_content_key": prepared["content_key"], "provider": provider, **SCOPE_FIELDS}, rules=certificate["rules"], evidence=core.scene_evidence(directory))
    require(ok, f"engineering scene content changed: {reasons}")
    render = evaluate_scene_render_manifest(read_json(directory / "renders" / "render_manifest.json"), read_json(directory / "layout_plan.json"))
    geometry = read_json(directory / "geometry_qa.json")
    check_scope(geometry)
    automated = bool(render["accepted"] and geometry["accepted"] and read_json(directory / "assembly_report.json").get("ok"))
    review_path = directory / "engineering_scene_review.json"
    review_ok, review_error = False, None
    if review_path.is_file():
        try:
            review = read_json(review_path)
            check_scope(review)
            template = scene_review_template(directory, certificate, read_json(output / "scene_request.json")["content_key"])
            for key in ("schema", "scene_glb_sha256", "content_certificate_hash", "request_content_key"):
                require(review.get(key) == template[key], f"scene review binding mismatch: {key}")
            require(review.get("reviewer") and review.get("original_quality_findings_acknowledged") is True, "scene review/negative-quality acknowledgment missing")
            actual_rgb = {bound(Path(row["rgb_path"]))["sha256"] for row in render["views"].values()}
            reviewed_rgb = {check_binding(binding) and binding["sha256"] for binding in review.get("reviewed_rgb_images", [])}
            require(actual_rgb and actual_rgb <= reviewed_rgb, "scene review missing real RGB images")
            checks = review.get("checks", [])
            require(len(checks) == len(template["checks"]) and {row["requirement_id"] for row in checks} == {row["requirement_id"] for row in template["checks"]}, "scene review checklist incomplete")
            require(all(row.get("status") == "pass" and str(row.get("observation") or "").strip() for row in checks), "scene review requirement unknown or failed")
            review_ok = True
        except (OSError, ValueError, TypeError, KeyError) as exc:
            review_error = str(exc)
    return {**SCOPE_FIELDS, "provider": provider, "automated_engineering_accepted": automated, "engineering_accepted": automated and review_ok, "status": "engineering_accepted" if automated and review_ok else ("engineering_scene_review_required" if automated and not review_path.is_file() else "engineering_incomplete_or_rejected"),
            "scene_glb": bound(scene), "content_certificate_hash": certificate["certificate_hash"], "review_error": review_error, "scene_review": bound(review_path) if review_path.is_file() else None, "render_images": {key: str(path) for key, path in core.scene_evidence(directory).items() if path.suffix == ".png"}, "original_quality_findings": prepared["scenes"][provider]["original_quality_findings"], "geometry_qa": str(directory / "geometry_qa.json")}


def verify(root: Path) -> dict[str, Any]:
    prepared = verify_prepared(root)
    scenes = {}
    for provider in PROVIDERS:
        try:
            scenes[provider] = verify_scene(root, provider)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            scenes[provider] = {**SCOPE_FIELDS, "provider": provider, "engineering_accepted": False, "automated_engineering_accepted": False, "status": "engineering_incomplete_or_invalid", "error": f"{type(exc).__name__}: {exc}"}
    report = {"schema": SCHEMA, **SCOPE_FIELDS, "engineering_accepted": all(row["engineering_accepted"] for row in scenes.values()), "automated_engineering_accepted": all(row["automated_engineering_accepted"] for row in scenes.values()), "engineering_prepared_content_key": prepared["content_key"], "scenes": scenes, "p021_physics_evaluated": False}
    write_json(root / "engineering_scene_validation" / "engineering_scene_validation_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("freeze", "prepare", "run", "verify"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--blender", type=Path, default=Path("/data/wsj/tools/blender/blender"))
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument("--provider", choices=PROVIDERS)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    require(128 <= args.resolution <= 2048, "resolution must be 128..2048")
    if args.command in {"freeze", "prepare", "verify"}:
        report = {"freeze": freeze, "prepare": prepare, "verify": verify}[args.command](root)
    else:
        report = run(root, args.blender.resolve(), args.resolution, args.provider)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    automated = report.get("scenes", {}).get(args.provider, {}).get("automated_engineering_accepted") if args.provider else report.get("automated_engineering_accepted")
    return 0 if args.command in {"freeze", "prepare"} or report.get("engineering_accepted") or (args.command == "run" and automated) else 2


if __name__ == "__main__":
    raise SystemExit(main())
