"""Executable, versioned contracts for Scene V2 production documents."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from .content_chain import content_hash
from .stage_dag import STAGES


CONTRACT_SCHEMA = "scene-v2-coordinate-contract/v1"
HEX_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class CoordinateContract:
    units: str = "m"
    handedness: str = "right_handed"
    world_up: str = "+z"
    yaw_axis: str = "+z"
    yaw_positive: str = "counterclockwise"
    asset_boundary: str = "declared_asset_source_up_to_world_z_up"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SCHEMA,
            "units": self.units,
            "handedness": self.handedness,
            "world_up": self.world_up,
            "yaw_axis": self.yaw_axis,
            "yaw_positive": self.yaw_positive,
            "asset_boundary": self.asset_boundary,
            "allowed_asset_source_up": ["+y", "+z"],
            "canonical_front_axes": ["+x", "-x", "+y", "-y"],
            "unknown_field_policy": "reject",
        }


COORDINATES = CoordinateContract()


class ContractError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX_DIGITS


def _require_exact_schema(document: dict[str, Any], schema: str, kind: str) -> None:
    _require(document.get("schema") == schema, f"{kind} schema mismatch")


def canonical_document_hash(document: dict[str, Any]) -> str:
    """Hash a document without its self-referential top-level content hash."""

    payload = {key: value for key, value in document.items() if key != "content_hash"}
    return content_hash(payload)


def stamp_document(document: dict[str, Any]) -> dict[str, Any]:
    document["content_hash"] = canonical_document_hash(document)
    return document


def validate_document_hash(document: dict[str, Any], *, required: bool = True) -> None:
    actual = document.get("content_hash")
    if actual is None and not required:
        return
    _require(_is_sha256(actual), "document content_hash must be lowercase SHA-256")
    _require(actual == canonical_document_hash(document), "document content_hash mismatch")


def require_coordinate_contract(document: dict[str, Any]) -> None:
    _require(document.get("coordinate_contract") == COORDINATES.as_dict(), "coordinate contract mismatch")


def _validate_dimensions(value: Any, label: str) -> None:
    _require(isinstance(value, dict), f"{label} dimensions must be an object")
    for axis in ("width", "length", "height"):
        item = value.get(axis)
        _require(
            isinstance(item, (int, float)) and not isinstance(item, bool) and float(item) > 0.0,
            f"{label} {axis} must be positive metres",
        )


def _validate_instance_groups(document: dict[str, Any], object_ids: set[str]) -> None:
    groups = document.get("instance_groups")
    _require(isinstance(groups, list), "instance_groups must be explicit")
    group_ids: set[str] = set()
    member_to_group: dict[str, str] = {}
    for group in groups:
        _require(isinstance(group, dict), "instance group must be an object")
        group_id = group.get("group_id")
        _require(isinstance(group_id, str) and bool(group_id), "instance group_id is required")
        _require(group_id not in group_ids, f"duplicate instance group: {group_id}")
        group_ids.add(group_id)
        members = group.get("members")
        _require(isinstance(members, list) and bool(members), f"group {group_id} needs members")
        for member_entry in members:
            if isinstance(member_entry, str):
                member = member_entry
            else:
                _require(isinstance(member_entry, dict), f"invalid member in group {group_id}")
                _require(set(member_entry) <= {"object_id", "role"}, f"unknown group-member field in {group_id}")
                member = member_entry.get("object_id")
                _require(isinstance(member_entry.get("role"), str), f"group-member role missing in {group_id}")
            _require(member in object_ids, f"unknown group member: {member}")
            _require(member not in member_to_group, f"object belongs to multiple groups: {member}")
            member_to_group[str(member)] = group_id
    for obj in document.get("objects", []):
        group_id = obj.get("instance_group_id")
        if group_id is not None:
            _require(group_id in group_ids, f"orphan instance_group_id for {obj.get('id')}: {group_id}")
            _require(member_to_group.get(str(obj.get("id"))) == group_id, f"group membership mismatch for {obj.get('id')}")


def validate_scene_brief(document: dict[str, Any]) -> None:
    _require_exact_schema(document, "codex_trellis_scene_brief_v2", "SceneBrief")
    require_coordinate_contract(document)
    _require(isinstance(document.get("original_prompt"), str), "SceneBrief original_prompt is required")
    _require(isinstance(document.get("room_type"), str), "SceneBrief room_type is required")
    _validate_dimensions(document.get("room"), "room")
    objects = document.get("objects")
    _require(isinstance(objects, list), "SceneBrief objects must be a list")
    object_ids: set[str] = set()
    for obj in objects:
        _require(isinstance(obj, dict), "SceneBrief object must be an object")
        object_id = obj.get("id")
        _require(isinstance(object_id, str) and bool(object_id), "SceneBrief object id is required")
        _require(object_id not in object_ids, f"duplicate SceneBrief object: {object_id}")
        object_ids.add(object_id)
        _require(isinstance(obj.get("category"), str), f"category missing for {object_id}")
        _validate_dimensions(obj.get("dimensions"), object_id)
    _validate_instance_groups(document, object_ids)
    validate_document_hash(document)


def validate_typed_scene_graph(document: dict[str, Any]) -> None:
    _require_exact_schema(document, "codex_trellis_typed_scene_graph_v1", "TypedSceneGraph")
    require_coordinate_contract(document)
    nodes = document.get("nodes")
    relations = document.get("relations")
    _require(isinstance(nodes, list), "TypedSceneGraph nodes must be a list")
    _require(isinstance(relations, list), "TypedSceneGraph relations must be a list")
    node_ids: set[str] = set()
    for node in nodes:
        _require(isinstance(node, dict), "graph node must be an object")
        node_id = node.get("id")
        _require(isinstance(node_id, str) and bool(node_id), "graph node id is required")
        _require(node_id not in node_ids, f"duplicate graph node: {node_id}")
        node_ids.add(node_id)
    _require(document.get("root_id") in node_ids, "graph root_id must resolve")
    for node in nodes:
        parent = node.get("parent_id")
        _require(parent is None or parent in node_ids, f"graph parent does not resolve: {parent}")
    for relation in relations:
        _require(isinstance(relation, dict), "graph relation must be an object")
        _require(relation.get("source") in node_ids, "graph relation source does not resolve")
        _require(relation.get("target") in node_ids, "graph relation target does not resolve")
        _require(isinstance(relation.get("type"), str), "graph relation type is required")
    validation = document.get("validation")
    _require(isinstance(validation, dict) and isinstance(validation.get("ok"), bool), "graph validation status is required")
    validate_document_hash(document)


def validate_asset_qa_certificate(document: dict[str, Any]) -> None:
    _require_exact_schema(document, "scene-v2-content-certificate/v1", "AssetQACertificate")
    _require(set(document) == {"schema", "artifact", "upstream", "rules", "evidence", "certificate_hash"}, "unknown AssetQACertificate fields rejected")
    artifact = document.get("artifact")
    _require(isinstance(artifact, dict), "asset certificate artifact binding is required")
    _require(isinstance(artifact.get("bytes"), int) and artifact["bytes"] >= 0, "asset artifact bytes invalid")
    _require(_is_sha256(artifact.get("sha256")), "asset artifact SHA-256 invalid")
    _require(isinstance(document.get("upstream"), dict), "asset certificate upstream is required")
    _require(isinstance(document.get("rules"), dict), "asset certificate rules are required")
    evidence = document.get("evidence")
    _require(isinstance(evidence, dict), "asset certificate evidence is required")
    for binding in evidence.values():
        _require(isinstance(binding, dict) and _is_sha256(binding.get("sha256")), "asset evidence binding invalid")
    certificate_hash = document.get("certificate_hash")
    _require(_is_sha256(certificate_hash), "asset certificate hash invalid")
    payload = {key: value for key, value in document.items() if key != "certificate_hash"}
    _require(certificate_hash == content_hash(payload), "asset certificate hash mismatch")


def validate_layout_plan(plan: dict[str, Any]) -> None:
    _require_exact_schema(plan, "codex_trellis_layout_plan_v2", "LayoutPlan")
    require_coordinate_contract(plan)
    objects = plan.get("objects")
    _require(isinstance(objects, list), "layout objects must be a list")
    object_ids: set[str] = set()
    for obj in objects:
        _require(isinstance(obj, dict), "layout object must be an object")
        object_id = obj.get("id")
        _require(isinstance(object_id, str) and bool(object_id), "layout object id is required")
        _require(object_id not in object_ids, f"duplicate layout object: {object_id}")
        object_ids.add(object_id)
        unknown_legacy = {"rotation", "rotation_y", "rotation_z", "heading", "up_axis"}.intersection(obj)
        _require(not unknown_legacy, f"legacy orientation fields rejected: {sorted(unknown_legacy)}")
        yaw = obj.get("yaw")
        _require(isinstance(yaw, (int, float)) and not isinstance(yaw, bool) and 0.0 <= float(yaw) < 360.0, f"invalid yaw for {object_id}: {yaw}")
        source_up = obj.get("asset_source_up", "+z")
        _require(source_up in {"+y", "+z"}, f"invalid asset source up for {object_id}: {source_up}")
        axis = obj.get("asset_axis_to_z", 1 if source_up == "+y" else 2)
        _require(axis in {1, 2}, f"invalid asset_axis_to_z for {object_id}: {axis}")
        _require((source_up == "+y" and axis == 1) or (source_up == "+z" and axis == 2), f"asset up-axis mapping mismatch for {object_id}")
        front = obj.get("asset_canonical_front")
        if front is not None:
            _require(isinstance(front, dict) and set(front) <= {"axis", "source", "confidence"}, f"unknown canonical-front field for {object_id}")
            _require(front.get("axis") in {"+x", "-x", "+y", "-y"}, f"invalid canonical front for {object_id}")
        role = obj.get("asset_pair_role")
        _require(role is None or role in {"left", "right"}, f"invalid handedness role for {object_id}")
    _validate_instance_groups(plan, object_ids)
    validate_document_hash(plan)


def validate_relation_certificate(document: dict[str, Any]) -> None:
    schema = document.get("schema")
    allowed = {"relation_geometry_certificate_v1", "codex_trellis_relation_geometry_audit_v1", "scene-v2-production-relation-geometry-stage/v1"}
    _require(schema in allowed, "RelationCertificate schema mismatch")
    _require(isinstance(document.get("ok"), bool), "RelationCertificate ok status is required")
    if schema == "codex_trellis_relation_geometry_audit_v1":
        _require(isinstance(document.get("relations"), list), "relation audit relations must be a list")
        _require(isinstance(document.get("relation_count"), int), "relation_count is required")
        _require(document["relation_count"] == len(document["relations"]), "relation_count mismatch")
    validate_document_hash(document, required=False)


def validate_run_manifest(document: dict[str, Any]) -> None:
    _require_exact_schema(document, "scene-v2-stage-dag/v1", "RunManifest")
    _require(document.get("stage_order") == list(STAGES), "RunManifest stage order mismatch")
    stages = document.get("stages")
    _require(isinstance(stages, dict) and set(stages) == set(STAGES), "RunManifest stages mismatch")
    for stage in STAGES:
        record = stages[stage]
        _require(isinstance(record.get("attempts"), list), f"attempts missing for {stage}")
        for number, attempt in enumerate(record["attempts"], start=1):
            _require(attempt.get("schema") == "scene-v2-stage-attempt/v1", f"attempt schema mismatch for {stage}")
            _require(attempt.get("attempt") == number, f"attempt numbering mismatch for {stage}")
            _require(attempt.get("status") in {"running", "committed", "failed"}, f"attempt status invalid for {stage}")
            _require(_is_sha256(attempt.get("input_key")), f"attempt input_key invalid for {stage}")
            if attempt.get("status") == "committed":
                _require(_is_sha256(attempt.get("output_key")), f"attempt output_key invalid for {stage}")
    validate_document_hash(document)


def validate_final_delivery_audit(document: dict[str, Any]) -> None:
    _require_exact_schema(document, "scene-v2-final-hash-audit/v1", "FinalDeliveryAudit")
    _require(isinstance(document.get("ok"), bool), "FinalDeliveryAudit ok status is required")
    _require(isinstance(document.get("missing"), list), "FinalDeliveryAudit missing must be a list")
    artifacts = document.get("artifacts")
    _require(isinstance(artifacts, dict), "FinalDeliveryAudit artifacts must be an object")
    for name, binding in artifacts.items():
        _require(isinstance(binding, dict), f"artifact binding invalid: {name}")
        _require(set(binding) == {"bytes", "sha256"}, f"unknown artifact binding field: {name}")
        _require(isinstance(binding.get("bytes"), int) and binding["bytes"] >= 0, f"artifact bytes invalid: {name}")
        _require(_is_sha256(binding.get("sha256")), f"artifact SHA-256 invalid: {name}")
    _require(not document["ok"] or not document["missing"], "successful final audit cannot have missing artifacts")
    validate_document_hash(document)


def migrate_layout_plan(document: dict[str, Any]) -> dict[str, Any]:
    schema = str(document.get("schema") or "")
    _require(schema in {"codex_trellis_layout_plan_v1", "codex_trellis_layout_plan_v2"}, f"no explicit layout migration for schema: {schema or '<missing>'}")
    migrated = deepcopy(document)
    migrated.pop("content_hash", None)
    migrated["schema"] = "codex_trellis_layout_plan_v2"
    migrated["coordinate_contract"] = COORDINATES.as_dict()
    migrated.setdefault("instance_groups", [])
    for obj in migrated.get("objects", []):
        if "yaw_degrees" in obj and "yaw" not in obj:
            obj["yaw"] = obj.pop("yaw_degrees")
        obj.setdefault("asset_source_up", "+z")
        obj.setdefault("asset_axis_to_z", 2)
    stamp_document(migrated)
    validate_layout_plan(migrated)
    return migrated


def migrate_document(kind: str, document: dict[str, Any]) -> dict[str, Any]:
    if kind == "LayoutPlan":
        return migrate_layout_plan(document)
    raise ContractError(f"no explicit migration registered for {kind} schema: {document.get('schema')}")


def validate_document_family(kind: str, document: dict[str, Any]) -> None:
    validators: dict[str, Callable[[dict[str, Any]], None]] = {
        "SceneBrief": validate_scene_brief,
        "TypedSceneGraph": validate_typed_scene_graph,
        "AssetQACertificate": validate_asset_qa_certificate,
        "LayoutPlan": validate_layout_plan,
        "RelationCertificate": validate_relation_certificate,
        "RunManifest": validate_run_manifest,
        "FinalDeliveryAudit": validate_final_delivery_audit,
    }
    validator = validators.get(kind)
    if validator is None:
        raise ContractError(f"unknown document family: {kind}")
    validator(document)
