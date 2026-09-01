from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from .collision_proxy import load_normalized_asset_mesh
from .mesh_verifier import (
    PreparedTriangleMesh,
    intersection_tolerance,
    prepare_triangle_mesh,
    verify_mesh_intersection,
)
from .multilevel_proxy import load_multilevel_proxy, mesh_content_hash
from .relation_geometry import (
    RELATION_SLOT_TYPES,
    DistanceProxy,
    compile_relation_geometry,
    evaluate_relation_geometry,
    pose_matrix,
)


RELATION_GEOMETRY_BINDING_SCHEMA = "codex_trellis_relation_geometry_binding_v1"
RELATION_GEOMETRY_AUDIT_SCHEMA = "codex_trellis_relation_geometry_audit_v1"
RELATION_GEOMETRY_VALIDATION_SCHEMA = "codex_trellis_relation_geometry_validation_v1"


GEOMETRY_WAIVABLE_AABB_RELATIONS = {
    "contained_in",
    "partially_inserted",
    "tucked_under",
}


@dataclass
class RuntimeGeometryAsset:
    capability: dict[str, Any]
    surface_points_local: np.ndarray
    proxy: DistanceProxy
    proxy_hash: str
    mesh: trimesh.Trimesh | None = None


def load_runtime_geometry_asset(
    capability: dict[str, Any],
    *,
    asset_root: Path,
    proxy_manifest_path: Path,
    surface_sample_count: int = 20_000,
    verify_hash: bool = True,
) -> RuntimeGeometryAsset:
    if surface_sample_count < 100:
        raise ValueError("surface_sample_count must be at least 100")
    mesh, _ = load_normalized_asset_mesh(
        capability, asset_root, verify_hash=verify_hash
    )
    proxy = load_multilevel_proxy(proxy_manifest_path)
    expected_mesh_hash = str(proxy.manifest.get("mesh_hash") or "")
    level_mesh_hash = str(proxy.metadata.get("mesh_hash") or "")
    actual_mesh_hash = mesh_content_hash(mesh)
    if expected_mesh_hash != level_mesh_hash or expected_mesh_hash != actual_mesh_hash:
        raise ValueError("proxy is stale for the normalized runtime mesh")
    points, _ = trimesh.sample.sample_surface(
        mesh, int(surface_sample_count), seed=17
    )
    return RuntimeGeometryAsset(
        capability=capability,
        surface_points_local=np.asarray(points, dtype=np.float64),
        proxy=proxy,
        proxy_hash=str(proxy.manifest["build_hash"]),
        mesh=mesh,
    )


def validate_geometry_binding(binding: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(binding, dict):
        return {"ok": False, "error_count": 1, "errors": ["binding must be an object"]}
    if binding.get("schema") != RELATION_GEOMETRY_BINDING_SCHEMA:
        errors.append(f"schema must be {RELATION_GEOMETRY_BINDING_SCHEMA}")
    relations = binding.get("relations")
    if not isinstance(relations, list) or not relations:
        errors.append("relations must be a non-empty list")
        relations = []
    seen: set[tuple[str, str, str]] = set()
    for index, relation in enumerate(relations):
        prefix = f"relations[{index}]"
        if not isinstance(relation, dict):
            errors.append(f"{prefix} must be an object")
            continue
        relation_type = str(relation.get("relation_type") or "")
        if relation_type not in RELATION_SLOT_TYPES:
            errors.append(f"{prefix}.relation_type is unsupported")
        required = ("source_object_id", "target_object_id", "target_slot_id")
        for key in required:
            if not str(relation.get(key) or ""):
                errors.append(f"{prefix}.{key} must be non-empty")
        key = (
            str(relation.get("source_object_id") or ""),
            relation_type,
            str(relation.get("target_object_id") or ""),
        )
        if key in seen:
            errors.append(f"duplicate relation binding: {key}")
        seen.add(key)
        if relation.get("triangle_verification", "critical_only") not in {
            "off",
            "critical_only",
            "always",
        }:
            errors.append(
                f"{prefix}.triangle_verification must be off, critical_only, or always"
            )
    return {"ok": not errors, "error_count": len(errors), "errors": errors}


def _relation_parts(item: Any) -> tuple[str, str, str, str]:
    if isinstance(item, (list, tuple)) and len(item) == 3:
        return str(item[0]), str(item[1]), str(item[2]), "hard"
    if isinstance(item, dict):
        return (
            str(item.get("source") or item.get("subject") or ""),
            str(item.get("type") or item.get("predicate") or ""),
            str(item.get("target") or item.get("object") or ""),
            str(item.get("strength") or "soft"),
        )
    return "", "", "", ""


def _require_hard_relation(
    plan: dict[str, Any], source: str, relation_type: str, target: str
) -> None:
    for item in plan.get("relations", []):
        parts = _relation_parts(item)
        if parts[:3] == (source, relation_type, target):
            if parts[3] != "hard":
                raise ValueError(
                    f"geometry-bound relation must be hard: {source} {relation_type} {target}"
                )
            return
    raise KeyError(f"missing hard relation: {source} {relation_type} {target}")


def _object_pose(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "x": float(obj.get("x", 0.0)),
        "y": float(obj.get("y", 0.0)),
        "z": float(obj.get("z", 0.0)),
        "yaw_degrees": float(obj.get("yaw", 0.0)),
    }


def _is_critical(certificate: dict[str, Any]) -> bool:
    collision = certificate["collision"]
    for direction in ("source_to_target", "target_to_source"):
        report = collision[direction]
        if not report.get("complete"):
            return True
        if int(report.get("deep_count", 0)) or int(report.get("ambiguous_count", 0)):
            return True
    return False


def evaluate_geometry_bindings(
    plan: dict[str, Any],
    binding: dict[str, Any],
    runtime_assets: dict[str, RuntimeGeometryAsset],
) -> dict[str, Any]:
    """Opt-in geometry audit for any supported relation primitive."""

    validation = validate_geometry_binding(binding)
    if not validation["ok"]:
        raise ValueError("invalid geometry binding: " + "; ".join(validation["errors"]))
    objects = {
        str(obj["id"]): obj
        for obj in plan.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    }
    reports: list[dict[str, Any]] = []
    prepared_target_cache: dict[
        tuple[str, tuple[float, ...], float], PreparedTriangleMesh
    ] = {}
    for relation_binding in binding["relations"]:
        source_id = str(relation_binding["source_object_id"])
        target_id = str(relation_binding["target_object_id"])
        relation_type = str(relation_binding["relation_type"])
        _require_hard_relation(plan, source_id, relation_type, target_id)
        if source_id not in objects or target_id not in objects:
            raise KeyError(f"geometry binding endpoint is missing: {source_id}, {target_id}")
        source_object = objects[source_id]
        target_object = objects[target_id]
        source_asset_id = str(
            relation_binding.get("source_asset_id") or source_object.get("asset_id") or ""
        )
        target_asset_id = str(
            relation_binding.get("target_asset_id") or target_object.get("asset_id") or ""
        )
        if source_asset_id not in runtime_assets or target_asset_id not in runtime_assets:
            raise KeyError(
                f"runtime geometry asset is missing: {source_asset_id}, {target_asset_id}"
            )
        source_asset = runtime_assets[source_asset_id]
        target_asset = runtime_assets[target_asset_id]
        contract = compile_relation_geometry(
            {
                "type": relation_type,
                "target_slot_id": relation_binding["target_slot_id"],
                "source_anchor_id": relation_binding.get("source_anchor_id"),
                "verification_policy": relation_binding.get(
                    "verification_policy", "conservative_bilateral"
                ),
                "contact_tolerance_m": relation_binding.get("contact_tolerance_m"),
            },
            source_asset.capability,
            target_asset.capability,
        )
        source_pose = _object_pose(source_object)
        target_pose = _object_pose(target_object)
        evaluation = evaluate_relation_geometry(
            contract,
            source_points_local=source_asset.surface_points_local,
            target_points_local=target_asset.surface_points_local,
            source_pose=source_pose,
            target_pose=target_pose,
            source_proxy=source_asset.proxy,
            target_proxy=target_asset.proxy,
            proxy_hashes={
                "source": source_asset.proxy_hash,
                "target": target_asset.proxy_hash,
            },
        )
        certificate = evaluation.certificate
        triangle_policy = str(
            relation_binding.get("triangle_verification") or "critical_only"
        )
        critical = _is_critical(certificate)
        run_triangle = triangle_policy == "always" or (
            triangle_policy == "critical_only" and critical
        )
        triangle_report = None
        accepted = evaluation.accepted
        if run_triangle:
            if source_asset.mesh is None or target_asset.mesh is None:
                accepted = False
                triangle_report = {
                    "complete": False,
                    "reason": "critical pair has no triangle meshes",
                }
            else:
                pair_tolerance = intersection_tolerance(
                    source_asset.mesh, target_asset.mesh
                )
                target_pose_key = tuple(
                    float(value)
                    for row in np.asarray(
                        pose_matrix(target_pose)
                    ).round(12)
                    for value in row
                )
                cache_key = (
                    target_asset_id,
                    target_pose_key,
                    float(pair_tolerance),
                )
                prepared_target = prepared_target_cache.get(cache_key)
                target_cache_hit = prepared_target is not None
                if prepared_target is None:
                    prepared_target = prepare_triangle_mesh(
                        target_asset.mesh,
                        transform=target_pose,
                        tolerance=pair_tolerance,
                    )
                    prepared_target_cache[cache_key] = prepared_target
                triangle_report = verify_mesh_intersection(
                    source_asset.mesh,
                    target_asset.mesh,
                    first_transform=source_pose,
                    second_transform=target_pose,
                    prepared_second=prepared_target,
                )
                triangle_report["target_bvh_cache_hit"] = target_cache_hit
                if not triangle_report["complete"]:
                    accepted = False
                elif contract["evaluator"] in {"full_containment", "partial_entry"}:
                    accepted = bool(accepted and not triangle_report["intersects"])
        reports.append(
            {
                "source_object_id": source_id,
                "relation_type": relation_type,
                "target_object_id": target_id,
                "target_slot_id": relation_binding["target_slot_id"],
                "accepted": bool(accepted),
                "critical": critical,
                "triangle_verification": triangle_report,
                "certificate": certificate,
            }
        )
    return {
        "schema": RELATION_GEOMETRY_AUDIT_SCHEMA,
        "opt_in": True,
        "ok": all(report["accepted"] for report in reports),
        "relation_count": len(reports),
        "accepted_relation_count": sum(bool(report["accepted"]) for report in reports),
        "relations": reports,
    }


def reconcile_layout_validation_with_geometry_audit(
    validation: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    """Replace only proven AABB false positives with geometry certificates.

    A floor-object AABB overlap may be intentional for containment or partial
    insertion.  It is waived only when the exact object pair has an accepted
    bilateral proxy certificate and a completed triangle check with no surface
    intersection.  All unrelated validation failures remain unchanged.
    """

    if audit.get("schema") != RELATION_GEOMETRY_AUDIT_SCHEMA:
        raise ValueError(f"audit schema must be {RELATION_GEOMETRY_AUDIT_SCHEMA}")
    accepted_pairs: dict[frozenset[str], dict[str, Any]] = {}
    for report in audit.get("relations", []):
        if not isinstance(report, dict) or not report.get("accepted"):
            continue
        if str(report.get("relation_type")) not in GEOMETRY_WAIVABLE_AABB_RELATIONS:
            continue
        triangle = report.get("triangle_verification")
        if not isinstance(triangle, dict) or not triangle.get("complete") or triangle.get("intersects"):
            continue
        certificate = report.get("certificate")
        collision = certificate.get("collision") if isinstance(certificate, dict) else None
        if not isinstance(collision, dict) or not collision.get("complete"):
            continue
        if any(
            int(collision.get(direction, {}).get("deep_count", 0) or 0) != 0
            for direction in ("source_to_target", "target_to_source")
        ):
            continue
        pair = frozenset(
            (str(report.get("source_object_id")), str(report.get("target_object_id")))
        )
        if len(pair) == 2:
            accepted_pairs[pair] = report

    reconciled = deepcopy(validation)
    retained: list[dict[str, Any]] = []
    waived: list[dict[str, Any]] = []
    for violation in reconciled.get("violations", []):
        object_ids = violation.get("objects") if isinstance(violation, dict) else None
        pair = (
            frozenset(str(item) for item in object_ids)
            if isinstance(object_ids, list) and len(object_ids) == 2
            else frozenset()
        )
        report = accepted_pairs.get(pair)
        if violation.get("type") == "floor_collision" and report is not None:
            waived.append(
                {
                    "violation": violation,
                    "relation_type": report["relation_type"],
                    "source_object_id": report["source_object_id"],
                    "target_object_id": report["target_object_id"],
                    "certificate_hash": report["certificate"].get("certificate_hash"),
                    "reason": "bilateral geometry certificate and triangle verification supersede AABB overlap",
                }
            )
        else:
            retained.append(violation)

    hard = [item for item in retained if item.get("severity") == "hard"]
    soft = [item for item in retained if item.get("severity") == "soft"]
    reconciled.update(
        {
            "schema": RELATION_GEOMETRY_VALIDATION_SCHEMA,
            "base_validation_schema": validation.get("schema"),
            "ok": not hard,
            "hard_violation_count": len(hard),
            "soft_violation_count": len(soft),
            "violations": retained,
            "geometry_waived_violation_count": len(waived),
            "geometry_waived_violations": waived,
            "geometry_audit_schema": audit.get("schema"),
        }
    )
    return reconciled
