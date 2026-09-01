from __future__ import annotations

import argparse
import json
import math
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from .capabilities import capability_index, load_capability_registry
from .collision_mesh_cleanup import (
    CollisionMeshCleanupConfig,
    cleanup_collision_mesh,
)
from .collision_proxy import load_normalized_asset_mesh, sha256_file
from .content_chain import verify_artifact_certificate
from .gltf_export import export_z_up_scene_glb
from .instance_groups import (
    apply_instance_group_postprocess,
    deterministic_pair_groups,
    member_handedness_role,
    recover_orphan_matched_groups,
)
from .io_utils import read_json, write_json
from .multilevel_proxy import (
    ProxyLevelSpec,
    compile_multilevel_proxy,
    load_multilevel_proxy,
    mesh_content_hash,
    save_multilevel_proxy,
)
from .relation_geometry import compile_relation_geometry, pose_matrix
from .relation_geometry_bridge import (
    RELATION_GEOMETRY_AUDIT_SCHEMA,
    RELATION_GEOMETRY_BINDING_SCHEMA,
    RuntimeGeometryAsset,
    evaluate_geometry_bindings,
)
from .relation_solver import optimize_relation_pose
from .orientation import (
    apply_facing_constraints,
    physical_contact_wall,
)
from .resource_health import (
    ResourceHealthThresholds,
    append_health_checkpoint,
)
from .whole_scene_audit import (
    attach_glb_audit,
    audit_glb_world_transforms,
    audit_plan,
    normalize_relation_parent_fields,
    refresh_typed_scene_graph,
)


SCHEMA = "codex_trellis_sdf_complex_bedroom_v2"
DEFAULT_BASE_RUN = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "bedroom_complete_relation_geometry_20260822_v1"
)
DEFAULT_ASSET_ROOT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1"
)
DEFAULT_OUTPUT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "sdf_complex_bedroom_trellis2_20260829_v2"
)
DEFAULT_TRELLIS_ASSET_DIR = DEFAULT_OUTPUT / "trellis_assets"
DEFAULT_BLENDER = Path("/data/wsj/tools/blender/blender")
CAPABILITY_REGISTRY = (
    Path(__file__).parent / "capabilities" / "pilot_desk_chair_v1.json"
)
GEOMETRY_ASSET_IDS = (
    "desk_warm_oak_001",
    "office_chair_black_mesh_001",
    "open_bookcase_trellis2_001",
    "book_row_trellis2_001",
    "book_row_trellis2_002",
    "book_row_trellis2_003",
)
GEOMETRY_RELATION_IDS = ("chair", "book_1", "book_2", "book_3")
LAUNCH_THRESHOLDS = ResourceHealthThresholds(minimum_mem_available_gib=96.0)
RUNTIME_THRESHOLDS = ResourceHealthThresholds(minimum_mem_available_gib=64.0)
MAXIMUM_TASK_RSS_GIB = 12.0

TRELLIS_ASSET_SPECS: tuple[dict[str, Any], ...] = (
    {
        "asset_id": "open_bookcase_trellis2_001",
        "object_id": "sdf_open_bookcase",
        "category": "bookcase",
        "dimensions": {"width": 0.90, "length": 0.36, "height": 1.90},
    },
    {
        "asset_id": "book_row_trellis2_001",
        "object_id": "sdf_books_1",
        "category": "book_stack",
        "dimensions": {"width": 0.34, "length": 0.14, "height": 0.37},
        "slot_id": "lower_bay",
    },
    {
        "asset_id": "book_row_trellis2_002",
        "object_id": "sdf_books_2",
        "category": "book_stack",
        "dimensions": {"width": 0.34, "length": 0.14, "height": 0.37},
        "slot_id": "middle_bay",
    },
    {
        "asset_id": "book_row_trellis2_003",
        "object_id": "sdf_books_3",
        "category": "book_stack",
        "dimensions": {"width": 0.34, "length": 0.14, "height": 0.37},
        "slot_id": "upper_bay",
    },
)
TRELLIS_ASSET_INDEX = {str(item["asset_id"]): item for item in TRELLIS_ASSET_SPECS}
CURATED_ORIENTATION_KEYS = (
    "asset_axis_to_z",
    "asset_axis_to_z_sign",
    "asset_local_yaw_offset_degrees",
    "footprint_yaw_offset_degrees",
    "asset_canonical_front",
    "asset_medial_axis",
    "asset_orientation",
    "asset_affordance",
    "usage_constraints",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        temporary.write(
            (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(
                "utf-8"
            )
        )
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _atomic_save_points(path: Path, points: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        np.savez_compressed(temporary, points=np.asarray(points, dtype=np.float64))
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _process_tree_rss_gib(root_pid: int) -> float:
    processes: dict[int, tuple[int, int]] = {}
    for status_path in Path("/proc").glob("[0-9]*/status"):
        try:
            values: dict[str, str] = {}
            for line in status_path.read_text(encoding="utf-8").splitlines():
                if line.startswith(("Pid:", "PPid:", "VmRSS:")):
                    key, value = line.split(":", 1)
                    values[key] = value.strip().split()[0]
            pid = int(values["Pid"])
            processes[pid] = (int(values["PPid"]), int(values.get("VmRSS", "0")))
        except (FileNotFoundError, KeyError, PermissionError, ProcessLookupError, ValueError):
            continue
    members = {int(root_pid)}
    changed = True
    while changed:
        changed = False
        for pid, (parent, _) in processes.items():
            if parent in members and pid not in members:
                members.add(pid)
                changed = True
    rss_kib = sum(processes.get(pid, (0, 0))[1] for pid in members)
    return float(rss_kib) / (1024.0**2)


def _run_monitored_subprocess(
    command: list[str],
    *,
    output: Path,
    stage: str,
    log_path: Path,
    checkpoint_path: Path,
    monitor_interval_seconds: float = 5.0,
) -> dict[str, Any]:
    """Run one heavy child with persistent logs and resource-triggered SIGTERM."""

    started_utc = _utc_now()
    started_monotonic = time.monotonic()
    launch_health: dict[str, Any] | None = None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
    )
    process: subprocess.Popen[str] | None = None
    last_rss_gib = 0.0
    maximum_rss_gib = 0.0
    rss_over_limit_samples = 0
    io_pressure_samples = 0
    termination_reason: str | None = None
    return_code: int | None = None
    error: str | None = None
    try:
        launch_health = append_health_checkpoint(
            output / "resource_health.jsonl",
            stage=f"{stage}_launch",
            require_healthy=True,
            thresholds=LAUNCH_THRESHOLDS,
        )
        with log_path.open("a", encoding="utf-8") as log_handle:
            log_handle.write(
                f"[{started_utc}] START stage={stage} command={json.dumps(command)}\n"
            )
            log_handle.flush()
            os.fsync(log_handle.fileno())
            process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                env=environment,
                start_new_session=True,
            )
            while process.poll() is None:
                sample_started = time.monotonic()
                last_rss_gib = _process_tree_rss_gib(process.pid)
                maximum_rss_gib = max(maximum_rss_gib, last_rss_gib)
                health = append_health_checkpoint(
                    output / "resource_health.jsonl",
                    stage=f"{stage}_monitor",
                    require_healthy=False,
                    thresholds=RUNTIME_THRESHOLDS,
                )
                metrics = health["metrics"]
                rss_over_limit_samples = (
                    rss_over_limit_samples + 1
                    if last_rss_gib > MAXIMUM_TASK_RSS_GIB
                    else 0
                )
                io_pressure = bool(
                    max(
                        int(metrics["blocked_processes_before"]),
                        int(metrics["blocked_processes_after"]),
                    )
                    > 16
                    or float(metrics["iowait_fraction"]) > 0.35
                )
                io_pressure_samples = io_pressure_samples + 1 if io_pressure else 0
                if rss_over_limit_samples >= 2:
                    termination_reason = "task_rss_above_12_gib_twice"
                elif float(metrics["mem_available_gib"]) < 64.0:
                    termination_reason = "mem_available_below_64_gib"
                elif float(metrics["dirty_writeback_gib"]) > 4.0:
                    termination_reason = "dirty_writeback_above_4_gib"
                elif io_pressure_samples >= 3:
                    termination_reason = "blocked_or_iowait_pressure_three_samples"
                if termination_reason is not None:
                    log_handle.write(
                        f"[{_utc_now()}] SIGTERM reason={termination_reason} "
                        f"rss_gib={last_rss_gib:.6f}\n"
                    )
                    log_handle.flush()
                    os.fsync(log_handle.fileno())
                    os.killpg(process.pid, signal.SIGTERM)
                    break
                remaining = monitor_interval_seconds - (time.monotonic() - sample_started)
                if remaining > 0:
                    time.sleep(remaining)
            return_code = process.wait()
            final_rss_gib = _process_tree_rss_gib(process.pid)
            if final_rss_gib > 0.0:
                last_rss_gib = final_rss_gib
                maximum_rss_gib = max(maximum_rss_gib, final_rss_gib)
            log_handle.write(
                f"[{_utc_now()}] END stage={stage} return_code={return_code} "
                f"max_rss_gib={maximum_rss_gib:.6f}\n"
            )
            log_handle.flush()
            os.fsync(log_handle.fileno())
    except BaseException as caught:
        error = f"{type(caught).__name__}: {caught}"
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            return_code = process.wait()
        raise
    finally:
        ended_utc = _utc_now()
        signal_number = -return_code if return_code is not None and return_code < 0 else None
        checkpoint = {
            "schema": SCHEMA,
            "stage": stage,
            "started_utc": started_utc,
            "ended_utc": ended_utc,
            "elapsed_seconds": float(time.monotonic() - started_monotonic),
            "command": command,
            "log": str(log_path),
            "exit_code": return_code if return_code is not None and return_code >= 0 else None,
            "signal": signal_number,
            "last_rss_gib": float(last_rss_gib),
            "maximum_rss_gib": float(maximum_rss_gib),
            "termination_reason": termination_reason,
            "launch_health": launch_health,
            "error": error,
            "ok": bool(return_code == 0 and termination_reason is None and error is None),
        }
        _atomic_write_json(checkpoint_path, checkpoint)
    if return_code != 0 or termination_reason is not None:
        raise RuntimeError(
            f"{stage} failed with return code {return_code}"
            + (f" ({termination_reason})" if termination_reason else "")
            + f"; see {log_path}"
        )
    return checkpoint


def _hardlink_tree(source: Path, target: Path) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            continue
        try:
            os.link(path, destination)
        except OSError:
            shutil.copy2(path, destination)


def _hardlink_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) == sha256_file(source):
            return
        raise FileExistsError(
            f"staged asset already exists with different content: {destination}"
        )
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _trellis_capability(asset_id: str, trellis_asset_dir: Path) -> dict[str, Any]:
    spec = TRELLIS_ASSET_INDEX[asset_id]
    source_glb = trellis_asset_dir / f"{asset_id}.glb"
    if not source_glb.is_file():
        raise FileNotFoundError(source_glb)
    capability: dict[str, Any] = {
        "schema": "codex_trellis_asset_capability_v1",
        "asset_id": asset_id,
        "category": spec["category"],
        "source_asset": {
            "sha256": sha256_file(source_glb),
            "qa_status": "scene_specific_multiview_approved",
        },
        "coordinate_frame": {
            "units": "meters",
            "up_axis": "z",
            "origin": "footprint_center_base",
            # trimesh observes the raw TRELLIS glTF coordinates before Blender's
            # glTF importer performs its automatic Y-up to Z-up conversion.
            "source_mesh_up_axis": "y",
            "source_mesh_up_sign": 1.0,
            "asset_local_yaw_offset_degrees": 0.0,
            "canonical_dimensions": dict(spec["dimensions"]),
        },
        "collision_proxy": {
            "representation": "multilevel_voxel_sdf",
            "source_glb": f"{asset_id}.glb",
            "source_requires_watertight": False,
        },
        "support_surfaces": [],
        "containment_volumes": [],
        "free_space_volumes": [],
        "semantic_anchors": [],
    }
    if asset_id == "open_bookcase_trellis2_001":
        capability["containment_volumes"] = [
            {
                "id": "lower_bay",
                "shape": "box",
                "min_m": [-0.34, -0.12, 0.10],
                "max_m": [0.34, 0.12, 0.56],
                "clearance_m": 0.01,
                "allowed_categories": ["book_stack"],
                "provenance": "scene_specific_reviewed_three_bay_trellis2_bookcase",
            },
            {
                "id": "middle_bay",
                "shape": "box",
                "min_m": [-0.34, -0.12, 0.68],
                "max_m": [0.34, 0.12, 1.14],
                "clearance_m": 0.01,
                "allowed_categories": ["book_stack"],
                "provenance": "scene_specific_reviewed_three_bay_trellis2_bookcase",
            },
            {
                "id": "upper_bay",
                "shape": "box",
                "min_m": [-0.34, -0.12, 1.26],
                "max_m": [0.34, 0.12, 1.79],
                "clearance_m": 0.01,
                "allowed_categories": ["book_stack"],
                "provenance": "scene_specific_reviewed_three_bay_trellis2_bookcase",
            },
        ]
    return capability


def _require_trellis_multiview_qa(trellis_asset_dir: Path) -> dict[str, Any]:
    qa_path = trellis_asset_dir / "multiview_qa.json"
    if not qa_path.is_file():
        raise FileNotFoundError(
            f"TRELLIS multiview QA gate is missing: {qa_path}"
        )
    qa = read_json(qa_path)
    if qa.get("schema") != "codex_trellis_multiview_qa_v2":
        raise RuntimeError(
            "TRELLIS multiview QA uses an unbound legacy schema; regenerate or "
            "migrate it with content certificates"
        )
    accepted_rows = {
        str(item.get("asset_id")): item
        for item in qa.get("assets", [])
        if isinstance(item, dict) and bool(item.get("accepted"))
    }
    accepted = set(accepted_rows)
    required = set(TRELLIS_ASSET_INDEX)
    missing = sorted(required - accepted)
    if not bool(qa.get("ok")) or missing:
        raise RuntimeError(
            "TRELLIS multiview QA did not approve every required asset: "
            + ", ".join(missing or sorted(required))
        )
    for asset_id in sorted(required):
        row = accepted_rows[asset_id]
        glb = trellis_asset_dir / f"{asset_id}.glb"
        if not glb.is_file():
            raise FileNotFoundError(glb)
        expected_glb_hash = str(row.get("glb_sha256") or "")
        actual_glb_hash = sha256_file(glb)
        if not expected_glb_hash or actual_glb_hash != expected_glb_hash:
            raise RuntimeError(
                f"TRELLIS multiview QA GLB hash mismatch for {asset_id}: "
                f"expected={expected_glb_hash or '<missing>'} actual={actual_glb_hash}"
            )
        contact_sheet_value = str(row.get("contact_sheet") or "")
        expected_sheet_hash = str(row.get("contact_sheet_sha256") or "")
        if not contact_sheet_value or not expected_sheet_hash:
            raise RuntimeError(
                f"TRELLIS multiview QA evidence hash is missing for {asset_id}"
            )
        contact_sheet = (qa_path.parent / contact_sheet_value).resolve()
        if not contact_sheet.is_file():
            raise FileNotFoundError(contact_sheet)
        actual_sheet_hash = sha256_file(contact_sheet)
        if actual_sheet_hash != expected_sheet_hash:
            raise RuntimeError(
                f"TRELLIS multiview QA contact-sheet hash mismatch for {asset_id}: "
                f"expected={expected_sheet_hash} actual={actual_sheet_hash}"
            )
        generation_contract = row.get("generation_contract")
        qa_rules = row.get("qa_rules")
        certificate = row.get("content_certificate")
        if not all(
            isinstance(value, dict)
            for value in (generation_contract, qa_rules, certificate)
        ):
            raise RuntimeError(
                f"TRELLIS multiview QA content chain is incomplete for {asset_id}"
            )
        if not generation_contract.get("content_key"):
            raise RuntimeError(
                f"TRELLIS multiview QA generation key is missing for {asset_id}"
            )
        required_rule_fields = {
            "renderer_binary",
            "renderer_script",
            "camera_contract",
            "qa_rules_version",
        }
        if required_rule_fields.difference(qa_rules):
            raise RuntimeError(
                f"TRELLIS multiview QA renderer/camera/rules binding is incomplete for {asset_id}"
            )
        views = row.get("views")
        required_views = {"front", "back", "left", "right"}
        if not isinstance(views, dict) or required_views.difference(views):
            raise RuntimeError(
                f"TRELLIS multiview QA four-view evidence is incomplete for {asset_id}"
            )
        evidence = {"contact_sheet": contact_sheet}
        for view_name in sorted(required_views):
            view_path = (qa_path.parent / str(views[view_name])).resolve()
            if not view_path.is_file():
                raise FileNotFoundError(view_path)
            evidence[f"view_{view_name}"] = view_path
        valid, reasons = verify_artifact_certificate(
            certificate,
            glb,
            upstream={"generation_contract": generation_contract},
            rules=qa_rules,
            evidence=evidence,
        )
        if not valid:
            raise RuntimeError(
                f"TRELLIS multiview QA certificate mismatch for {asset_id}: "
                + ", ".join(reasons)
            )
    return qa


def _curated_manifest_index(asset_root: Path) -> dict[str, dict[str, Any]]:
    manifest_path = asset_root / "manifest.json"
    payload = read_json(manifest_path)
    assets = payload.get("assets", []) if isinstance(payload, dict) else []
    if not isinstance(assets, list):
        raise ValueError(f"curated asset manifest has no assets list: {manifest_path}")
    return {
        str(item["asset_id"]): item
        for item in assets
        if isinstance(item, dict) and item.get("asset_id")
    }


def _lateral_reflection_axis(asset: dict[str, Any]) -> str:
    front = asset.get("asset_canonical_front")
    front = front if isinstance(front, dict) else {}
    front_axis = str(front.get("axis") or "+y").lower().lstrip("+-")
    return "y" if front_axis == "x" else "x"


def _refresh_instance_group_assets(
    plan: dict[str, Any], manifest: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    objects = [
        item
        for item in plan.get("objects", [])
        if isinstance(item, dict) and item.get("id")
    ]
    by_id = {str(item["id"]): item for item in objects}
    refreshed: list[dict[str, Any]] = []
    for group in plan.get("instance_groups", []):
        if not isinstance(group, dict):
            continue
        contract = group.get("asset_contract")
        contract = contract if isinstance(contract, dict) else {}
        requires_handedness = bool(contract.get("requires_handedness", False))
        for member in group.get("members", []):
            if not isinstance(member, dict):
                continue
            object_id = str(member.get("object_id") or "")
            obj = by_id.get(object_id)
            if obj is None:
                continue
            asset_id = str(obj.get("asset_id") or "")
            asset = manifest.get(asset_id)
            if asset is None:
                continue
            for key in CURATED_ORIENTATION_KEYS:
                if key in asset:
                    obj[key] = deepcopy(asset[key])
            obj["instance_group_id"] = str(group.get("group_id") or "")
            if not requires_handedness:
                continue
            desired_role = member_handedness_role(member)
            source_role = str(asset.get("pair_role") or "")
            semantics = str(asset.get("pair_role_semantics") or "")
            if not desired_role or not source_role or not semantics:
                raise RuntimeError(
                    f"handed instance group metadata is incomplete for {object_id}"
                )
            obj["asset_pair_role"] = desired_role
            obj["asset_source_pair_role"] = source_role
            obj["asset_pair_role_semantics"] = semantics
            if isinstance(asset.get("pair_role_qa"), dict):
                obj["asset_pair_role_qa"] = deepcopy(asset["pair_role_qa"])
            obj["instance_group_asset_family"] = f"mirror_pair:{asset_id}"
            if desired_role != source_role:
                obj["asset_reflection_axis"] = _lateral_reflection_axis(asset)
                obj["asset_reflection_space"] = "canonical_asset_local"
                obj["asset_reflection_source_asset_id"] = asset_id
                obj["asset_handedness_provenance"] = "local_reflection_pair"
                obj["instance_group_asset_strategy"] = "local_mirror_fallback"
            else:
                obj.pop("asset_reflection_axis", None)
                obj.pop("asset_reflection_space", None)
                obj.pop("asset_reflection_source_asset_id", None)
                obj["asset_handedness_provenance"] = "mirror_pair_primary"
                obj["instance_group_asset_strategy"] = "mirror_pair_primary"
            refreshed.append(
                {
                    "group_id": str(group.get("group_id") or ""),
                    "object_id": object_id,
                    "asset_id": asset_id,
                    "requested_pair_role": desired_role,
                    "source_pair_role": source_role,
                    "reflection_axis": obj.get("asset_reflection_axis"),
                }
            )
    return refreshed


def _reconcile_soft_wall_facing(plan: dict[str, Any]) -> list[dict[str, Any]]:
    room = plan.get("room") if isinstance(plan.get("room"), dict) else {}
    objects = [item for item in plan.get("objects", []) if isinstance(item, dict)]
    wall_changes: list[dict[str, Any]] = []
    for obj in objects:
        constraint = obj.get("facing_constraint")
        if not isinstance(constraint, dict) or str(constraint.get("mode")) != "into_room":
            continue
        if str(obj.get("wall_constraint_strength") or "hard") == "hard":
            continue
        actual_wall = physical_contact_wall(obj, room)
        if actual_wall is None:
            continue
        previous_preference = str(obj.get("preferred_wall") or "")
        previous_constraint_wall = str(constraint.get("wall") or previous_preference)
        if actual_wall == previous_preference and actual_wall == previous_constraint_wall:
            continue
        obj["preferred_wall"] = actual_wall
        obj["resolved_wall"] = actual_wall
        updated_constraint = deepcopy(constraint)
        updated_constraint["wall"] = actual_wall
        updated_constraint["requested_wall"] = previous_constraint_wall
        updated_constraint["wall_resolution_source"] = "physical_contact_wall_persisted"
        obj["facing_constraint"] = updated_constraint
        wall_changes.append(
            {
                "object_id": str(obj.get("id") or ""),
                "from_preferred_wall": previous_preference,
                "from_constraint_wall": previous_constraint_wall,
                "to_resolved_wall": actual_wall,
                "reason": "soft_wall_abandoned_follow_physical_contact",
            }
        )
    yaw_changes = apply_facing_constraints(objects, room)
    return [*wall_changes, *yaw_changes]


def _whole_scene_regression_audit(
    plan: dict[str, Any], relation_audit: dict[str, Any] | None = None
) -> dict[str, Any]:
    return audit_plan(plan, relation_audit)


def _repair_inherited_scene_contracts(
    plan: dict[str, Any], asset_root: Path
) -> dict[str, Any]:
    objects = [
        item
        for item in plan.get("objects", [])
        if isinstance(item, dict) and item.get("id")
    ]
    groups = [item for item in plan.get("instance_groups", []) if isinstance(item, dict)]
    if not any(str(item.get("group_id")) == "explicit_slipper_pair" for item in groups):
        generated = deterministic_pair_groups(
            str(plan.get("description") or ""), objects, {"slipper": 2}
        )
        groups.extend(generated)
    plan["instance_groups"] = groups
    recovered_legacy_groups = recover_orphan_matched_groups(plan)
    refreshed_assets = _refresh_instance_group_assets(
        plan, _curated_manifest_index(asset_root)
    )
    group_resolution = apply_instance_group_postprocess(plan)
    plan["instance_group_resolution"] = group_resolution
    orientation_changes = _reconcile_soft_wall_facing(plan)
    plan["orientation_resolution"] = [
        *[
            item
            for item in plan.get("orientation_resolution", [])
            if isinstance(item, dict)
        ],
        *orientation_changes,
    ]
    refresh_typed_scene_graph(plan)
    audit = _whole_scene_regression_audit(plan)
    report = {
        "schema": "codex_trellis_inherited_scene_contract_repair_v1",
        "ok": bool(audit["ok"]),
        "refreshed_instance_group_assets": refreshed_assets,
        "recovered_legacy_instance_groups": recovered_legacy_groups,
        "instance_group_resolution": group_resolution,
        "orientation_changes": orientation_changes,
        "whole_scene_pre_geometry_audit": audit,
    }
    if not report["ok"]:
        failed_gates = [
            key
            for key in (
                "typed_scene_graph",
                "functional_facing",
                "support_parent",
                "architecture_openings_and_entry",
                "operation_clearance",
                "layout_non_regression_gate",
            )
            if isinstance(audit.get(key), dict)
            and (
                audit[key].get("ok") is False
                or int(audit[key].get("failure_count", 0) or 0) > 0
            )
        ]
        raise RuntimeError(
            "inherited whole-scene semantic contracts remain invalid: "
            + ", ".join(failed_gates)
            + "; layout_failures="
            + ",".join(
                str(item.get("type") or "unknown")
                for item in audit.get("layout_non_regression_gate", {}).get(
                    "failures", []
                )
            )
        )
    return report


def _sample(mesh: trimesh.Trimesh, count: int = 8000) -> np.ndarray:
    points, _ = trimesh.sample.sample_surface(mesh, count, seed=20260829)
    return np.asarray(points, dtype=np.float64)


def _pose_from_matrix(matrix: np.ndarray) -> dict[str, float]:
    return {
        "x": float(matrix[0, 3]),
        "y": float(matrix[1, 3]),
        "z": float(matrix[2, 3]),
        "yaw": math.degrees(math.atan2(float(matrix[1, 0]), float(matrix[0, 0]))) % 360.0,
    }


def _layout_pose(item: dict[str, Any]) -> dict[str, float]:
    """Convert persisted layout fields to the relation-geometry pose contract."""

    return {
        "x": float(item.get("x", 0.0)),
        "y": float(item.get("y", 0.0)),
        "z": float(item.get("z", 0.0)),
        "yaw_degrees": float(item.get("yaw", item.get("yaw_degrees", 0.0))),
    }


def _object(plan: dict[str, Any], object_id: str) -> dict[str, Any]:
    for item in plan.get("objects", []):
        if str(item.get("id")) == object_id:
            return item
    raise KeyError(object_id)


def prepare_stage(
    base_run: Path, asset_root: Path, output: Path, trellis_asset_dir: Path
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    staged = output / "assets_staged"
    _hardlink_tree(base_run / "assets_staged", staged)
    plan = deepcopy(read_json(base_run / "layout_plan_final.json"))
    multiview_qa = _require_trellis_multiview_qa(trellis_asset_dir)
    inherited_contract_repair = _repair_inherited_scene_contracts(plan, asset_root)

    trellis_reports: list[dict[str, Any]] = []
    capabilities: dict[str, dict[str, Any]] = {}
    for spec in TRELLIS_ASSET_SPECS:
        asset_id = str(spec["asset_id"])
        source_glb = trellis_asset_dir / f"{asset_id}.glb"
        pilot_report_path = trellis_asset_dir / f"{asset_id}_pilot_report.json"
        if not pilot_report_path.is_file():
            raise FileNotFoundError(pilot_report_path)
        pilot_report = read_json(pilot_report_path)
        if not bool(pilot_report.get("ok")):
            raise RuntimeError(f"TRELLIS pilot report is not successful: {pilot_report_path}")
        inspection = pilot_report.get("inspection") or {}
        if not bool(inspection.get("trimesh_load_ok")):
            raise RuntimeError(f"TRELLIS GLB failed structural inspection: {source_glb}")
        capability = _trellis_capability(asset_id, trellis_asset_dir)
        capabilities[asset_id] = capability
        staged_glb = staged / f"{spec['object_id']}.glb"
        _hardlink_file(source_glb, staged_glb)
        trellis_reports.append(
            {
                "asset_id": asset_id,
                "object_id": str(spec["object_id"]),
                "source_glb": str(source_glb),
                "staged_glb": str(staged_glb),
                "sha256": sha256_file(source_glb),
                "pilot_report": str(pilot_report_path),
                "pilot_ok": True,
                "multiview_qa_accepted": True,
            }
        )

    bookcase_spec = TRELLIS_ASSET_SPECS[0]
    bookcase_capability = capabilities[str(bookcase_spec["asset_id"])]
    bookcase_id = "sdf_open_bookcase"
    book_specs = [dict(item) for item in TRELLIS_ASSET_SPECS[1:]]

    plan["objects"].append(
        {
            "id": bookcase_id,
            "category": "bookcase",
            "asset_id": bookcase_capability["asset_id"],
            "asset_source": "trellis2_scene_specific_multiview_approved",
            "asset_axis_to_z": 2,
            "asset_axis_to_z_sign": 1.0,
            "asset_local_yaw_offset_degrees": 0.0,
            "placement_type": "floor",
            "dimensions": dict(bookcase_spec["dimensions"]),
            "x": 4.66,
            "y": 4.22,
            "z": 0.0,
            "yaw": 0.0,
        }
    )
    for index, spec in enumerate(book_specs):
        plan["objects"].append(
            {
                "id": spec["object_id"],
                "category": "book_stack",
                "asset_id": spec["asset_id"],
                "asset_source": "trellis2_scene_specific_multiview_approved",
                "asset_axis_to_z": 2,
                "asset_axis_to_z_sign": 1.0,
                "asset_local_yaw_offset_degrees": 0.0,
                "placement_type": "contained",
                "container_id": bookcase_id,
                "dimensions": dict(spec["dimensions"]),
                "x": 4.66,
                "y": 4.16,
                "z": 0.12 + index * 0.58,
                "yaw": 0.0,
            }
        )
        plan.setdefault("relations", []).append(
            {
                "source": spec["object_id"],
                "type": "contained_in",
                "target": bookcase_id,
                "strength": "hard",
                "parameters": {"target_slot_id": spec["slot_id"]},
            }
        )
    plan["relationship_preview"] = {
        "camera_location": [0.75, -0.65, 2.65],
        "target": [4.48, 3.25, 1.0],
        "lens_mm": 52.0,
        "hidden_walls": ["south", "east"],
        "resolution_x": 1280,
        "resolution_y": 900,
        "target_object_ids": [
            "explicit_desk",
            "explicit_office_chair",
            bookcase_id,
            *[item["object_id"] for item in book_specs],
        ],
    }
    refresh_typed_scene_graph(plan)
    write_json(output / "layout_plan_pre_geometry.json", plan)
    write_json(
        output / "whole_scene_regression_audit_pre_geometry.json",
        inherited_contract_repair["whole_scene_pre_geometry_audit"],
    )
    write_json(
        output / "inherited_scene_contract_repair.json",
        inherited_contract_repair,
    )
    report = {
        "schema": SCHEMA,
        "stage": "prepare",
        "base_run": str(base_run),
        "base_assets_reused_by_hardlink": True,
        "trellis_asset_dir": str(trellis_asset_dir),
        "trellis_multiview_qa": multiview_qa,
        "bookcase_capability": bookcase_capability,
        "book_specs": book_specs,
        "trellis_asset_exports": trellis_reports,
        "inherited_scene_contract_repair": inherited_contract_repair,
        "procedural_asset_exports": [],
        "procedural_fallback_permitted": False,
    }
    write_json(output / "prepare_report.json", report)
    return report


def _asset_meshes(
    asset_id: str,
    *,
    asset_root: Path,
    trellis_asset_dir: Path,
) -> tuple[dict[str, Any], trimesh.Trimesh, trimesh.Trimesh, dict[str, Any] | None]:
    if asset_id in {"desk_warm_oak_001", "office_chair_black_mesh_001"}:
        capabilities = capability_index(load_capability_registry(CAPABILITY_REGISTRY))
        capability = capabilities[asset_id]
        visual_mesh, _ = load_normalized_asset_mesh(
            capability, asset_root, verify_hash=True
        )
    elif asset_id in TRELLIS_ASSET_INDEX:
        capability = _trellis_capability(asset_id, trellis_asset_dir)
        visual_mesh, _ = load_normalized_asset_mesh(
            capability, trellis_asset_dir, verify_hash=True
        )
    else:
        raise KeyError(f"unknown geometry asset id: {asset_id}")
    candidate, cleanup_report = cleanup_collision_mesh(
        visual_mesh,
        CollisionMeshCleanupConfig(
            maximum_components=512,
            minimum_retained_area_fraction=0.99,
            maximum_bounds_change_m=0.05,
        ),
    )
    collision_mesh = candidate if cleanup_report["accepted"] else visual_mesh
    cleanup_report["collision_proxy_uses_cleaned_mesh"] = bool(
        cleanup_report["accepted"]
    )
    cleanup_report["non_destructive_visual_mesh_preserved"] = True
    return capability, visual_mesh, collision_mesh, cleanup_report


def _compile_proxy_asset(
    *,
    asset_id: str,
    capability: dict[str, Any],
    collision_mesh: trimesh.Trimesh,
    output: Path,
    cleanup_report: dict[str, Any] | None,
) -> dict[str, Any]:
    proxy_directory = output / "collision_proxies" / asset_id
    manifest_path = proxy_directory / "manifest.json"
    proxy = None
    resumed = False
    if manifest_path.is_file():
        try:
            candidate = load_multilevel_proxy(manifest_path)
            if str(candidate.manifest.get("mesh_hash")) == mesh_content_hash(
                collision_mesh
            ):
                proxy = candidate
                resumed = True
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            proxy = None
    if proxy is None:
        proxy = compile_multilevel_proxy(
            collision_mesh,
            [ProxyLevelSpec("coarse", 0.04, 1), ProxyLevelSpec("fine", 0.02, 1)],
            maximum_split_components=512,
            metadata={
                "asset_id": asset_id,
                "collision_mesh_cleanup": cleanup_report,
                "visual_mesh_preserved_for_triangle_verification": True,
            },
        )
        manifest_path = save_multilevel_proxy(proxy, proxy_directory)
    surface_points_path = proxy_directory / "surface_points.npz"
    _atomic_save_points(surface_points_path, _sample(collision_mesh))
    _atomic_write_json(
        output / "geometry_progress.json",
        {
            "schema": SCHEMA,
            "last_completed_asset_id": asset_id,
            "proxy_manifest": str(manifest_path),
            "proxy_build_hash": str(proxy.manifest["build_hash"]),
            "resumed_existing_proxy": resumed,
        },
    )
    return {
        "asset_id": asset_id,
        "proxy_manifest": str(manifest_path),
        "surface_points": str(surface_points_path),
        "mesh_hash": str(proxy.manifest["mesh_hash"]),
        "proxy_build_hash": str(proxy.manifest["build_hash"]),
        "resumed_existing_proxy": resumed,
        "collision_mesh_cleanup": cleanup_report,
        "visual_mesh_preserved_for_triangle_verification": True,
    }


def geometry_asset_stage(
    asset_root: Path,
    trellis_asset_dir: Path,
    output: Path,
    asset_id: str,
) -> dict[str, Any]:
    if asset_id not in GEOMETRY_ASSET_IDS:
        raise KeyError(f"unsupported geometry asset worker: {asset_id}")
    append_health_checkpoint(
        output / "resource_health.jsonl",
        stage=f"geometry_asset_{asset_id}_start",
        require_healthy=True,
        thresholds=LAUNCH_THRESHOLDS,
    )
    capability, visual_mesh, collision_mesh, cleanup_report = _asset_meshes(
        asset_id,
        asset_root=asset_root,
        trellis_asset_dir=trellis_asset_dir,
    )
    if cleanup_report is not None:
        _atomic_write_json(
            output / "collision_cleanup" / f"{asset_id}.json", cleanup_report
        )
        if cleanup_report["accepted"]:
            export_z_up_scene_glb(
                collision_mesh,
                output / "collision_cleanup" / f"{asset_id}.collision.glb",
                overwrite=True,
            )
    report = _compile_proxy_asset(
        asset_id=asset_id,
        capability=capability,
        collision_mesh=collision_mesh,
        output=output,
        cleanup_report=cleanup_report,
    )
    report.update(
        {
            "schema": SCHEMA,
            "stage": "geometry_asset",
            "ok": True,
            "visual_face_count": int(len(visual_mesh.faces)),
            "collision_face_count": int(len(collision_mesh.faces)),
        }
    )
    _atomic_write_json(output / "geometry_assets" / f"{asset_id}.json", report)
    append_health_checkpoint(
        output / "resource_health.jsonl",
        stage=f"geometry_asset_{asset_id}_complete",
        require_healthy=False,
        thresholds=RUNTIME_THRESHOLDS,
    )
    return report


def _load_saved_runtime_asset(
    asset_id: str,
    *,
    asset_root: Path,
    trellis_asset_dir: Path,
    output: Path,
) -> RuntimeGeometryAsset:
    report_path = output / "geometry_assets" / f"{asset_id}.json"
    report = read_json(report_path)
    if not report.get("ok"):
        raise RuntimeError(f"geometry asset report is not complete: {report_path}")
    proxy = load_multilevel_proxy(Path(report["proxy_manifest"]))
    if str(proxy.manifest.get("mesh_hash")) != str(report.get("mesh_hash")):
        raise ValueError(f"proxy hash mismatch for {asset_id}")
    with np.load(Path(report["surface_points"])) as archive:
        points = np.asarray(archive["points"], dtype=np.float64)
    if asset_id in {"desk_warm_oak_001", "office_chair_black_mesh_001"}:
        capabilities = capability_index(load_capability_registry(CAPABILITY_REGISTRY))
        capability = capabilities[asset_id]
        visual_mesh, _ = load_normalized_asset_mesh(
            capability, asset_root, verify_hash=True
        )
    elif asset_id in TRELLIS_ASSET_INDEX:
        capability = _trellis_capability(asset_id, trellis_asset_dir)
        visual_mesh, _ = load_normalized_asset_mesh(
            capability, trellis_asset_dir, verify_hash=True
        )
    else:
        raise KeyError(asset_id)
    return RuntimeGeometryAsset(
        capability=capability,
        surface_points_local=points,
        proxy=proxy,
        proxy_hash=str(proxy.manifest["build_hash"]),
        mesh=visual_mesh,
    )


def geometry_relation_stage(
    asset_root: Path,
    trellis_asset_dir: Path,
    output: Path,
    relation_id: str,
) -> dict[str, Any]:
    if relation_id not in GEOMETRY_RELATION_IDS:
        raise KeyError(f"unsupported geometry relation worker: {relation_id}")
    plan = read_json(output / "layout_plan_pre_geometry.json")
    if relation_id == "chair":
        source_object_id = "explicit_office_chair"
        source_asset_id = "office_chair_black_mesh_001"
        target_object_id = "explicit_desk"
        target_asset_id = "desk_warm_oak_001"
        target_slot_id = "under_desk"
        source_anchor_id = "seat_front"
        relation_type = "tucked_under"
        preferred_pose = {
            "x": 0.0,
            "y": -0.555,
            "z": 0.0,
            "yaw_degrees": 180.0,
        }
        maximum_candidates = 2000
    else:
        index = int(relation_id.split("_", 1)[1]) - 1
        source_object_id = f"sdf_books_{index + 1}"
        source_asset_id = f"book_row_trellis2_{index + 1:03d}"
        target_object_id = "sdf_open_bookcase"
        target_asset_id = "open_bookcase_trellis2_001"
        target_slot_id = ("lower_bay", "middle_bay", "upper_bay")[index]
        source_anchor_id = None
        relation_type = "contained_in"
        preferred_pose = {
            "x": (-0.18, 0.16, -0.08)[index],
            "y": -0.025,
            "z": 0.10 + index * 0.58,
            "yaw_degrees": 0.0,
        }
        maximum_candidates = 4000

    runtime = {
        source_asset_id: _load_saved_runtime_asset(
            source_asset_id,
            asset_root=asset_root,
            trellis_asset_dir=trellis_asset_dir,
            output=output,
        ),
        target_asset_id: _load_saved_runtime_asset(
            target_asset_id,
            asset_root=asset_root,
            trellis_asset_dir=trellis_asset_dir,
            output=output,
        ),
    }
    source_object = _object(plan, source_object_id)
    target_object = _object(plan, target_object_id)
    target_pose = _layout_pose(target_object)
    contract = compile_relation_geometry(
        {
            "type": relation_type,
            "target_slot_id": target_slot_id,
            "source_anchor_id": source_anchor_id,
            "verification_policy": "conservative_bilateral",
        },
        runtime[source_asset_id].capability,
        runtime[target_asset_id].capability,
    )
    solver = optimize_relation_pose(
        contract,
        source_points_local=runtime[source_asset_id].surface_points_local,
        target_points_local=runtime[target_asset_id].surface_points_local,
        source_proxy=runtime[source_asset_id].proxy,
        target_proxy=runtime[target_asset_id].proxy,
        target_world_pose=target_pose,
        preferred_target_local_pose=preferred_pose,
        translation_step_m=0.025,
        maximum_candidates=maximum_candidates,
        source_mesh=runtime[source_asset_id].mesh,
        target_mesh=runtime[target_asset_id].mesh,
        triangle_verification="collision_relations",
    )
    source_world = pose_matrix(target_pose) @ pose_matrix(
        solver["selected_target_local_pose"]
    )
    source_world_pose = _pose_from_matrix(source_world)
    source_object.update(source_world_pose)
    relation_binding = {
        "source_object_id": source_object_id,
        "relation_type": relation_type,
        "target_object_id": target_object_id,
        "target_slot_id": target_slot_id,
        "triangle_verification": "always",
    }
    if source_anchor_id is not None:
        relation_binding["source_anchor_id"] = source_anchor_id
    binding = {
        "schema": RELATION_GEOMETRY_BINDING_SCHEMA,
        "relations": [relation_binding],
    }
    audit = evaluate_geometry_bindings(plan, binding, runtime)
    report = {
        "schema": SCHEMA,
        "stage": "geometry_relation",
        "relation_id": relation_id,
        "ok": bool(audit["ok"] and audit["accepted_relation_count"] == 1),
        "source_object_id": source_object_id,
        "source_world_pose": source_world_pose,
        "binding": relation_binding,
        "solver": solver,
        "audit": audit,
    }
    _atomic_write_json(output / "geometry_relations" / f"{relation_id}.json", report)
    if not report["ok"]:
        raise RuntimeError(f"geometry relation {relation_id} was not accepted")
    return report


def _finalize_geometry_stage(output: Path) -> dict[str, Any]:
    plan = read_json(output / "layout_plan_pre_geometry.json")
    relation_reports = [
        read_json(output / "geometry_relations" / f"{relation_id}.json")
        for relation_id in GEOMETRY_RELATION_IDS
    ]
    if not all(report.get("ok") for report in relation_reports):
        raise RuntimeError("one or more relation subprocess reports are incomplete")
    for relation_report in relation_reports:
        _object(plan, str(relation_report["source_object_id"])).update(
            relation_report["source_world_pose"]
        )
    refresh_typed_scene_graph(plan)
    binding = {
        "schema": RELATION_GEOMETRY_BINDING_SCHEMA,
        "relations": [report["binding"] for report in relation_reports],
    }
    relation_items = [
        relation
        for report in relation_reports
        for relation in report["audit"]["relations"]
    ]
    audit = {
        "schema": RELATION_GEOMETRY_AUDIT_SCHEMA,
        "opt_in": True,
        "ok": all(bool(item["accepted"]) for item in relation_items),
        "relation_count": len(relation_items),
        "accepted_relation_count": sum(bool(item["accepted"]) for item in relation_items),
        "relations": relation_items,
        "assembled_from_isolated_relation_subprocesses": True,
    }
    whole_scene_audit = _whole_scene_regression_audit(plan, audit)
    cleanup_reports = {
        asset_id: read_json(output / "geometry_assets" / f"{asset_id}.json").get(
            "collision_mesh_cleanup"
        )
        for asset_id in GEOMETRY_ASSET_IDS
    }
    chair_report = relation_reports[0]
    book_reports = relation_reports[1:]
    report = {
        "schema": SCHEMA,
        "stage": "geometry",
        "ok": bool(
            audit["ok"]
            and audit["accepted_relation_count"] == 4
            and whole_scene_audit["ok"]
        ),
        "isolated_asset_subprocess_count": len(GEOMETRY_ASSET_IDS),
        "isolated_relation_subprocess_count": len(GEOMETRY_RELATION_IDS),
        "cleanup_reports": cleanup_reports,
        "relation_count": audit["relation_count"],
        "accepted_relation_count": audit["accepted_relation_count"],
        "chair_world_pose": chair_report["source_world_pose"],
        "book_world_poses": [
            {"id": item["source_object_id"], **item["source_world_pose"]}
            for item in book_reports
        ],
        "whole_scene_regression_ok": bool(whole_scene_audit["ok"]),
    }
    _atomic_write_json(output / "relation_geometry_binding.json", binding)
    _atomic_write_json(output / "relation_geometry_audit.json", audit)
    _atomic_write_json(
        output / "relation_geometry_solver.json",
        {
            "chair": chair_report["solver"],
            "books": [
                {
                    "object_id": item["source_object_id"],
                    "slot_id": item["binding"]["target_slot_id"],
                    "solver": item["solver"],
                }
                for item in book_reports
            ],
        },
    )
    _atomic_write_json(output / "layout_plan_final.json", plan)
    _atomic_write_json(output / "whole_scene_regression_audit.json", whole_scene_audit)
    _atomic_write_json(output / "geometry_stage_report.json", report)
    if not report["ok"]:
        raise RuntimeError("relation geometry audit did not accept all four relations")
    return report


def geometry_stage(
    asset_root: Path, trellis_asset_dir: Path, output: Path
) -> dict[str, Any]:
    if not (output / "layout_plan_pre_geometry.json").is_file():
        raise FileNotFoundError("prepare stage is incomplete")
    asset_slugs = {
        "desk_warm_oak_001": "desk",
        "office_chair_black_mesh_001": "office_chair",
        "open_bookcase_trellis2_001": "bookcase",
        "book_row_trellis2_001": "books_1",
        "book_row_trellis2_002": "books_2",
        "book_row_trellis2_003": "books_3",
    }
    module = "sage.experiments.codex_trellis_scene_v2.build_sdf_complex_bedroom"
    for asset_id in GEOMETRY_ASSET_IDS:
        slug = asset_slugs[asset_id]
        _run_monitored_subprocess(
            [
                sys.executable,
                "-m",
                module,
                "--phase",
                "geometry-asset",
                "--asset-root",
                str(asset_root),
                "--trellis-assets-dir",
                str(trellis_asset_dir),
                "--output-dir",
                str(output),
                "--asset-id",
                asset_id,
            ],
            output=output,
            stage=f"geometry_{slug}",
            log_path=output / "logs" / f"geometry_{slug}.log",
            checkpoint_path=output / "checkpoints" / f"geometry_{slug}.exit.json",
        )
    for relation_id in GEOMETRY_RELATION_IDS:
        _run_monitored_subprocess(
            [
                sys.executable,
                "-m",
                module,
                "--phase",
                "geometry-relation",
                "--asset-root",
                str(asset_root),
                "--trellis-assets-dir",
                str(trellis_asset_dir),
                "--output-dir",
                str(output),
                "--relation-id",
                relation_id,
            ],
            output=output,
            stage=f"relation_{relation_id}",
            log_path=output / "logs" / f"relation_{relation_id}.log",
            checkpoint_path=output / "checkpoints" / f"relation_{relation_id}.exit.json",
        )
    report = _finalize_geometry_stage(output)
    append_health_checkpoint(
        output / "resource_health.jsonl",
        stage="geometry_complete",
        require_healthy=False,
        thresholds=RUNTIME_THRESHOLDS,
    )
    return report


def assemble_stage(
    output: Path,
    *,
    blender: Path,
    assembler: Path,
) -> dict[str, Any]:
    whole_scene_audit_path = output / "whole_scene_regression_audit.json"
    if not whole_scene_audit_path.is_file():
        raise FileNotFoundError(whole_scene_audit_path)
    whole_scene_audit = read_json(whole_scene_audit_path)
    if not bool(whole_scene_audit.get("ok")):
        raise RuntimeError("whole-scene semantic regression audit did not pass")
    append_health_checkpoint(
        output / "resource_health.jsonl",
        stage="blender_start",
        require_healthy=True,
        thresholds=LAUNCH_THRESHOLDS,
    )
    glb = output / "scene_sdf_complex_bedroom.glb"
    preview_left = output / "scene_front_45.png"
    preview_center = output / "scene_front_center_45.png"
    relationship_preview = output / "scene_relationships_bookshelf_desk.png"
    command = [
        str(blender),
        "--background",
        "--python",
        str(assembler),
        "--",
        "--plan",
        str(output / "layout_plan_final.json"),
        "--asset-dir",
        str(output / "assets_staged"),
        "--output-glb",
        str(glb),
        "--preview-image",
        str(preview_left),
        "--preview-image-center",
        str(preview_center),
        "--relationship-preview",
        str(relationship_preview),
    ]
    _run_monitored_subprocess(
        command,
        output=output,
        stage="blender_assembly",
        log_path=output / "blender_assembly.log",
        checkpoint_path=output / "checkpoints" / "blender_assembly.exit.json",
    )
    scene = trimesh.load(glb, force="scene")
    if not isinstance(scene, trimesh.Scene) or not scene.geometry:
        raise RuntimeError("final GLB contains no scene geometry")
    nodes = sorted(str(value) for value in scene.graph.nodes_geometry)
    required_prefixes = (
        "wardrobe",
        "explicit_slipper_1",
        "explicit_slipper_2",
        "explicit_desk",
        "explicit_office_chair",
        "sdf_open_bookcase",
        "sdf_books_1",
        "sdf_books_2",
        "sdf_books_3",
    )
    missing = [prefix for prefix in required_prefixes if not any(prefix in node for node in nodes)]
    plan = read_json(output / "layout_plan_final.json")
    relation_audit = read_json(output / "relation_geometry_audit.json")
    final_plan_audit = _whole_scene_regression_audit(plan, relation_audit)
    glb_world_transform_audit = audit_glb_world_transforms(plan, scene)
    final_whole_scene_audit = attach_glb_audit(
        final_plan_audit, glb_world_transform_audit
    )
    _atomic_write_json(
        output / "glb_world_transform_audit.json", glb_world_transform_audit
    )
    _atomic_write_json(
        output / "whole_scene_regression_audit.json", final_whole_scene_audit
    )
    report = {
        "schema": SCHEMA,
        "stage": "assembly",
        "ok": bool(not missing and final_whole_scene_audit["ok"]),
        "glb": str(glb),
        "glb_bytes": glb.stat().st_size,
        "geometry_count": len(scene.geometry),
        "node_count": len(nodes),
        "required_node_prefixes": list(required_prefixes),
        "missing_required_node_prefixes": missing,
        "target_feature_ok": bool(final_whole_scene_audit["target_feature_ok"]),
        "whole_scene_regression_ok": bool(final_whole_scene_audit["whole_scene_ok"]),
        "glb_world_transform_ok": bool(glb_world_transform_audit["ok"]),
        "previews": [str(preview_left), str(preview_center), str(relationship_preview)],
    }
    write_json(output / "assembly_report.json", report)
    append_health_checkpoint(
        output / "resource_health.jsonl",
        stage="blender_complete",
        require_healthy=False,
        thresholds=RUNTIME_THRESHOLDS,
    )
    if not report["ok"]:
        raise RuntimeError(
            "assembled GLB is missing required objects or failed whole-scene audit"
        )
    return report


def reaudit_existing_stage(source: Path, output: Path) -> dict[str, Any]:
    """Create a non-destructive P003 audit closure from an existing delivery."""

    source = source.resolve()
    output = output.resolve()
    if source == output:
        raise ValueError("source delivery and output directory must differ")
    required = (
        "layout_plan_final.json",
        "relation_geometry_audit.json",
        "scene_sdf_complex_bedroom.glb",
    )
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError("source delivery is incomplete: " + ", ".join(missing))
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"reaudit output must be new or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    _hardlink_tree(source, output)

    plan = read_json(output / "layout_plan_final.json")
    parent_field_repairs = normalize_relation_parent_fields(plan)
    recovered_legacy_groups = recover_orphan_matched_groups(plan)
    refresh_typed_scene_graph(plan)
    relation_audit = read_json(output / "relation_geometry_audit.json")
    plan_audit = _whole_scene_regression_audit(plan, relation_audit)
    scene_path = output / "scene_sdf_complex_bedroom.glb"
    scene = trimesh.load(scene_path, force="scene", process=False)
    if not isinstance(scene, trimesh.Scene) or not scene.geometry:
        raise RuntimeError("existing delivery GLB contains no scene geometry")
    glb_audit = audit_glb_world_transforms(plan, scene)
    final_audit = attach_glb_audit(plan_audit, glb_audit)

    assembly_report_path = output / "assembly_report.json"
    assembly_report = (
        read_json(assembly_report_path) if assembly_report_path.is_file() else {}
    )
    assembly_report.update(
        {
            "ok": bool(final_audit["ok"]),
            "glb": str(scene_path),
            "target_feature_ok": bool(final_audit["target_feature_ok"]),
            "whole_scene_regression_ok": bool(final_audit["whole_scene_ok"]),
            "glb_world_transform_ok": bool(glb_audit["ok"]),
            "reaudited_without_asset_regeneration": True,
        }
    )
    report = {
        "schema": "codex_trellis_existing_delivery_reaudit_v1",
        "ok": bool(final_audit["ok"]),
        "source_delivery": str(source),
        "output_dir": str(output),
        "source_glb_sha256": sha256_file(source / "scene_sdf_complex_bedroom.glb"),
        "output_glb_sha256": sha256_file(scene_path),
        "glb_content_reused_by_hardlink_or_copy": True,
        "asset_regeneration_performed": False,
        "parent_field_repairs": parent_field_repairs,
        "recovered_legacy_instance_groups": recovered_legacy_groups,
        "target_feature_ok": bool(final_audit["target_feature_ok"]),
        "whole_scene_ok": bool(final_audit["whole_scene_ok"]),
        "typed_scene_graph_ok": bool(final_audit["typed_scene_graph"]["ok"]),
        "support_parent_ok": not bool(final_audit["support_parent"]["failure_count"]),
        "architecture_openings_and_entry_ok": not bool(
            final_audit["architecture_openings_and_entry"]["failure_count"]
        ),
        "operation_clearance_ok": bool(final_audit["operation_clearance"]["ok"]),
        "glb_world_transform_ok": bool(glb_audit["ok"]),
    }
    _atomic_write_json(output / "layout_plan_final.json", plan)
    _atomic_write_json(output / "glb_world_transform_audit.json", glb_audit)
    _atomic_write_json(output / "whole_scene_regression_audit.json", final_audit)
    _atomic_write_json(assembly_report_path, assembly_report)
    _atomic_write_json(output / "p003_reaudit_report.json", report)
    if not report["ok"]:
        raise RuntimeError("existing delivery failed P003 whole-scene reaudit")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the SDF-verified complex bedroom with books in a shelf and a tucked chair."
    )
    parser.add_argument(
        "--phase",
        choices=(
            "prepare",
            "geometry",
            "geometry-asset",
            "geometry-relation",
            "assemble",
            "reaudit-existing",
            "all",
        ),
        default="all",
    )
    parser.add_argument("--base-run", type=Path, default=DEFAULT_BASE_RUN)
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument(
        "--trellis-assets-dir", type=Path, default=DEFAULT_TRELLIS_ASSET_DIR
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-delivery", type=Path)
    parser.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    parser.add_argument("--asset-id", choices=GEOMETRY_ASSET_IDS)
    parser.add_argument("--relation-id", choices=GEOMETRY_RELATION_IDS)
    parser.add_argument(
        "--assembler",
        type=Path,
        default=Path(__file__).parents[2] / "scripts" / "blender_assemble_sage_scene.py",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output_dir.resolve()
    if args.phase == "reaudit-existing":
        if args.source_delivery is None:
            raise ValueError("--source-delivery is required for reaudit-existing")
        report = reaudit_existing_stage(args.source_delivery, output)
        print(json.dumps(report, indent=2), flush=True)
        return 0
    if args.phase == "geometry-asset":
        if args.asset_id is None:
            raise ValueError("--asset-id is required for geometry-asset")
        report = geometry_asset_stage(
            args.asset_root.resolve(),
            args.trellis_assets_dir.resolve(),
            output,
            str(args.asset_id),
        )
        print(json.dumps(report, indent=2), flush=True)
        return 0
    if args.phase == "geometry-relation":
        if args.relation_id is None:
            raise ValueError("--relation-id is required for geometry-relation")
        report = geometry_relation_stage(
            args.asset_root.resolve(),
            args.trellis_assets_dir.resolve(),
            output,
            str(args.relation_id),
        )
        print(json.dumps(report, indent=2), flush=True)
        return 0
    if args.phase in {"prepare", "all"}:
        prepare_stage(
            args.base_run.resolve(),
            args.asset_root.resolve(),
            output,
            args.trellis_assets_dir.resolve(),
        )
    if args.phase in {"geometry", "all"}:
        geometry_stage(
            args.asset_root.resolve(), args.trellis_assets_dir.resolve(), output
        )
    if args.phase in {"assemble", "all"}:
        assemble_stage(
            output,
            blender=args.blender.resolve(),
            assembler=args.assembler.resolve(),
        )
    geometry_report = (
        read_json(output / "geometry_stage_report.json")
        if (output / "geometry_stage_report.json").is_file()
        else None
    )
    assembly_report = (
        read_json(output / "assembly_report.json")
        if (output / "assembly_report.json").is_file()
        else None
    )
    whole_scene_report = (
        read_json(output / "whole_scene_regression_audit.json")
        if (output / "whole_scene_regression_audit.json").is_file()
        else None
    )
    summary = {
        "schema": SCHEMA,
        "ok": bool(
            geometry_report
            and geometry_report.get("ok")
            and assembly_report
            and assembly_report.get("ok")
            and whole_scene_report
            and whole_scene_report.get("ok")
        ),
        "output_dir": str(output),
        "geometry": geometry_report,
        "assembly": assembly_report,
        "whole_scene_regression": whole_scene_report,
        "resource_health_log": str(output / "resource_health.jsonl"),
    }
    write_json(output / "run_summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
