from __future__ import annotations

import json
import hashlib
import shutil
import socket
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .asset_admission import build_missing_asset_subflow_contract
from .asset_index import AssetIndex
from .content_chain import (
    build_generation_contract,
    content_hash,
    file_binding,
    make_artifact_certificate,
    verify_artifact_certificate,
)

from .dimensions import (
    AXES,
    dimension_policy_for_category,
    dimension_preference_key,
    resolve_dimension_adaptation,
)
from .brief import (
    build_asset_generation_spec,
    finalize_integrated_component_resolution,
    render_asset_prompt,
)
from .io_utils import read_json, write_json
from .instance_groups import (
    member_group_index,
    member_handedness_role,
    requires_handed_pair,
)
from .orientation import solve_facing_yaw
from .scene_dna import (
    apply_scene_dna_to_generation_spec,
    build_harmony_certificate,
    build_scene_dna_contract,
    score_asset_candidate,
)
from .scene_dna_multiview import render_and_evaluate_generated_asset
from .scene_dna_feasibility import select_3d_candidate
from .scene_dna_semantic import Siglip2SemanticScorer


ORIENTATION_METADATA_KEYS = (
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


def _resolved_handedness_reflection_axis(
    requested_axis: str, source: dict[str, Any]
) -> str:
    if requested_axis in {"x", "y"}:
        return requested_axis
    front = source.get("asset_canonical_front")
    front = front if isinstance(front, dict) else {}
    front_axis = str(front.get("axis") or "+y").lower().lstrip("+-")
    return "y" if front_axis == "x" else "x"


def _opener():
    return urlrequest.build_opener(urlrequest.ProxyHandler({}))


def _get(url: str, timeout: float = 30.0) -> tuple[int, bytes, str]:
    try:
        with _opener().open(url, timeout=timeout) as response:
            return response.status, response.read(), response.headers.get("Content-Type", "")
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


def _post_json(url: str, payload: dict[str, Any], timeout: float = 30.0) -> tuple[int, dict[str, Any]]:
    req = urlrequest.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _opener().open(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read()
        try:
            decoded = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = {"error": body.decode("utf-8", errors="replace")}
        return exc.code, decoded


def bridge_health(trellis_url: str) -> dict[str, Any]:
    try:
        status, body, _ = _get(trellis_url.rstrip("/") + "/health", timeout=5.0)
        payload = json.loads(body.decode("utf-8")) if body else {}
        return {"ok": status == 200, "status": status, "payload": payload}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


class AssetRegistry:
    """Read-only curated asset manifest. Generated assets are staged separately."""

    def __init__(self, manifest_path: Path | None) -> None:
        self.manifest_path = manifest_path.resolve() if manifest_path else None
        self.root = self.manifest_path.parent if self.manifest_path else None
        self.assets: list[dict[str, Any]] = []
        self.index: AssetIndex | None = None
        self.index_queries: list[dict[str, Any]] = []
        self.batch_prefetch_report: dict[str, Any] | None = None
        if self.manifest_path:
            payload = read_json(self.manifest_path)
            raw_assets = payload.get("assets", []) if isinstance(payload, dict) else []
            if not isinstance(raw_assets, list):
                raise ValueError(f"asset manifest 'assets' must be a list: {self.manifest_path}")
            self.assets = [item for item in raw_assets if isinstance(item, dict)]
            index_path = self.manifest_path.with_suffix(".asset_index.sqlite")
            if index_path.is_file():
                try:
                    self.index = AssetIndex(index_path, expected_manifest=self.manifest_path)
                except ValueError:
                    if len(self.assets) >= 10_000:
                        raise

    def prefetch(self, queries: list[dict[str, Any]]) -> dict[str, Any] | None:
        if self.index is None:
            return None
        unique: dict[str, dict[str, Any]] = {}
        for query in queries:
            normalized = {
                "category": str(query["category"]),
                "styles": list(query.get("styles", [])),
            }
            unique[content_hash(normalized)] = normalized
        self.batch_prefetch_report = self.index.batch_query(
            [unique[key] for key in sorted(unique)]
        )
        return deepcopy(self.batch_prefetch_report)

    def find(
        self,
        category: str,
        styles: list[str],
        *,
        variant_index: int = 0,
        target_dimensions: dict[str, Any] | None = None,
        dimension_policy: dict[str, Any] | None = None,
        rejections: list[dict[str, Any]] | None = None,
        family_id: str | None = None,
        asset_id: str | None = None,
        pair_role: str | None = None,
        scene_dna_contract: dict[str, Any] | None = None,
        object_id: str = "",
    ) -> dict[str, Any] | None:
        candidates: list[tuple[tuple[Any, ...], str, dict[str, Any]]] = []
        wanted_styles = {style.lower() for style in styles}
        indexed_query = None
        candidate_assets = self.assets
        if self.index is not None:
            indexed_query = self.index.query(
                category=category,
                styles=styles,
                family_id=family_id,
                asset_id=asset_id,
                pair_role=pair_role,
            )
            self.index_queries.append(
                {
                    key: deepcopy(indexed_query[key])
                    for key in (
                        "index_version", "query_contract_hash", "cache_key",
                        "cache_hit", "hard_filtered_count", "ann_recall_limit",
                        "rerank_limit",
                    )
                }
            )
            candidate_assets = indexed_query["results"]
        for item in candidate_assets:
            if str(item.get("category")) != category:
                continue
            if family_id and str(item.get("asset_family_id") or "") != family_id:
                continue
            if asset_id and str(item.get("asset_id") or "") != asset_id:
                continue
            if pair_role and str(item.get("pair_role") or "") != pair_role:
                continue
            if str(item.get("qa_status", "approved")) != "approved":
                continue
            lifecycle = str(item.get("lifecycle_status") or "")
            if lifecycle and lifecycle != "curated":
                continue
            raw_path = item.get("glb_path") or item.get("asset_path")
            if not raw_path:
                continue
            path = Path(str(raw_path)).expanduser()
            if not path.is_absolute() and self.root:
                path = self.root / path
            if not path.is_file():
                continue
            item_styles = {str(style).lower() for style in item.get("styles", [])}
            style_score = len(wanted_styles & item_styles)
            resolved = dict(item)
            resolved["resolved_glb_path"] = str(path.resolve())
            scene_dna_score = score_asset_candidate(
                resolved,
                scene_dna_contract,
                object_id=object_id,
            )
            resolved["_scene_dna_score"] = scene_dna_score
            if target_dimensions is not None:
                effective_policy = (
                    deepcopy(item["dimension_policy"])
                    if isinstance(item.get("dimension_policy"), dict)
                    else deepcopy(
                        dimension_policy or dimension_policy_for_category(category)
                    )
                )
                dimension_resolution = resolve_dimension_adaptation(
                    item.get("dimensions"), target_dimensions, effective_policy
                )
                if not dimension_resolution["accepted"]:
                    if rejections is not None:
                        rejections.append(
                            {
                                "asset_id": str(item.get("asset_id", path.stem)),
                                "source": str(path.resolve()),
                                "dimension_resolution": dimension_resolution,
                            }
                        )
                    continue
                resolved["_dimension_policy"] = effective_policy
                resolved["_dimension_resolution"] = dimension_resolution
                dimension_rank, dimension_error = dimension_preference_key(
                    dimension_resolution
                )
            else:
                dimension_rank, dimension_error = 0, 0.0
            if scene_dna_contract:
                preference = (
                    dimension_rank,
                    dimension_error,
                    -float(scene_dna_score["score"]),
                    -style_score,
                )
            else:
                preference = (dimension_rank, dimension_error, -style_score)
            candidates.append(
                (preference, str(item.get("asset_id", path.stem)), resolved)
            )
        if not candidates:
            return None
        candidates.sort(key=lambda row: (row[0], row[1]))
        best_score = candidates[0][0]
        best_candidates = [row for row in candidates if row[0] == best_score]
        selected = best_candidates[int(variant_index) % len(best_candidates)][2]
        if indexed_query is not None:
            selected["_asset_index_retrieval"] = {
                "index_version": indexed_query["index_version"],
                "query_contract_hash": indexed_query["query_contract_hash"],
                "cache_key": indexed_query["cache_key"],
                "hard_filtered_count": indexed_query["hard_filtered_count"],
                "selected_from_rerank_count": len(candidate_assets),
            }
        return selected


def _copy_asset(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == destination.resolve():
        return
    shutil.copy2(source, destination)


CANDIDATE_CHECKPOINT_SCHEMA = "scene_dna_3d_candidate_checkpoint_v1"


def _candidate_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_checkpoint_path(record: dict[str, Any]) -> Path:
    return Path(str(record["path"])).parent.parent / "candidate_checkpoint.json"


def _candidate_certificate_inputs(
    obj: dict[str, Any], contract_hash: str, record: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    bridge = metadata.get("bridge_metadata")
    bridge = bridge if isinstance(bridge, dict) else {}
    reference_value = record.get("reference_image_path") or bridge.get(
        "reference_image_path"
    )
    reference = Path(str(reference_value)) if reference_value else None
    generation_contract = deepcopy(obj.get("asset_generation_contract"))
    generation_contract = generation_contract if isinstance(generation_contract, dict) else {}
    generation_contract.pop("content_key", None)
    generation_contract["seed"] = int(record["seed"])
    generation_contract["reference_image"] = (
        file_binding(reference) if reference is not None and reference.is_file() else None
    )
    generation_contract["content_key"] = content_hash(generation_contract)
    upstream = {
        "generation_contract": generation_contract,
        "generation_key": generation_contract["content_key"],
        "planning_generation_key": str(obj.get("asset_generation_key") or ""),
        "scene_dna_contract_hash": str(contract_hash),
        "seed": int(record["seed"]),
        "request_hash": content_hash(metadata.get("request") or {}),
    }
    rules = {
        "kind": "scene_dna_3d_candidate",
        "attempt": int(record["attempt"]),
        "candidate_rank": int(record.get("candidate_rank", 1)),
        "multiview_report_hash": content_hash(record.get("multiview")),
    }
    return upstream, rules


def persist_candidate_checkpoint(
    candidate_root: Path,
    obj: dict[str, Any],
    contract_hash: str,
    record: dict[str, Any],
) -> Path:
    candidate_path = Path(str(record["path"])).resolve()
    root = candidate_root.resolve()
    if not candidate_path.is_relative_to(root):
        raise ValueError(f"Candidate checkpoint path escapes root: {candidate_path}")
    if not candidate_path.is_file():
        raise FileNotFoundError(candidate_path)
    payload = {
        "schema": CANDIDATE_CHECKPOINT_SCHEMA,
        "object_id": str(obj["id"]),
        "category": str(obj["category"]),
        "scene_dna_contract_hash": str(contract_hash),
        "attempt": int(record["attempt"]),
        "candidate_rank": int(record.get("candidate_rank", 1)),
        "candidate_path": str(candidate_path),
        "candidate_size_bytes": candidate_path.stat().st_size,
        "candidate_sha256": _candidate_file_sha256(candidate_path),
        "record": deepcopy(record),
    }
    upstream, rules = _candidate_certificate_inputs(obj, contract_hash, record)
    payload["content_certificate"] = make_artifact_certificate(
        candidate_path,
        upstream=upstream,
        rules=rules,
    )
    checkpoint_path = _candidate_checkpoint_path(record)
    write_json(checkpoint_path, payload)
    return checkpoint_path


def load_candidate_checkpoints(
    candidate_root: Path,
    obj: dict[str, Any],
    contract_hash: str,
) -> dict[tuple[int, int], dict[str, Any]]:
    records: dict[tuple[int, int], dict[str, Any]] = {}
    if not candidate_root.is_dir():
        return records
    root = candidate_root.resolve()
    for checkpoint_path in sorted(candidate_root.glob("attempt_*/candidate_checkpoint.json")):
        try:
            payload = read_json(checkpoint_path)
            if payload.get("schema") != CANDIDATE_CHECKPOINT_SCHEMA:
                continue
            if str(payload.get("object_id")) != str(obj["id"]):
                continue
            if str(payload.get("category")) != str(obj["category"]):
                continue
            if str(payload.get("scene_dna_contract_hash")) != str(contract_hash):
                continue
            record = payload.get("record")
            if not isinstance(record, dict):
                continue
            candidate_path = Path(str(payload.get("candidate_path") or "")).resolve()
            if not candidate_path.is_relative_to(root) or not candidate_path.is_file():
                continue
            if candidate_path.stat().st_size != int(payload.get("candidate_size_bytes", -1)):
                continue
            if _candidate_file_sha256(candidate_path) != str(payload.get("candidate_sha256")):
                continue
            if Path(str(record.get("path") or "")).resolve() != candidate_path:
                continue
            metadata = record.get("metadata")
            if not isinstance(metadata, dict) or not str(metadata.get("job_id") or ""):
                continue
            upstream, rules = _candidate_certificate_inputs(obj, contract_hash, record)
            valid, _ = verify_artifact_certificate(
                payload.get("content_certificate")
                if isinstance(payload.get("content_certificate"), dict)
                else {},
                candidate_path,
                upstream=upstream,
                rules=rules,
            )
            if not valid:
                continue
            key = (int(payload["attempt"]), int(payload["candidate_rank"]))
            records[key] = deepcopy(record)
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return records


RETRYABLE = (
    TimeoutError,
    socket.timeout,
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
    URLError,
)


def _final_flux_prompt(metadata: dict[str, Any] | None) -> str | None:
    if not isinstance(metadata, dict):
        return None
    bridge_metadata = metadata.get("bridge_metadata")
    if not isinstance(bridge_metadata, dict):
        return None
    selected_id = str(bridge_metadata.get("selected_reference_job_id") or "")
    attempts = bridge_metadata.get("reference_attempts", [])
    if not isinstance(attempts, list):
        return None
    selected = next(
        (
            attempt
            for attempt in attempts
            if isinstance(attempt, dict)
            and str(attempt.get("reference_job_id") or "") == selected_id
        ),
        None,
    )
    if selected is None:
        selected = next((item for item in attempts if isinstance(item, dict)), None)
    prompt = selected.get("prompt") if isinstance(selected, dict) else None
    return str(prompt) if prompt else None


def _scene_dna_candidate_selection(
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    bridge_metadata = metadata.get("bridge_metadata")
    if not isinstance(bridge_metadata, dict):
        return None
    selection = bridge_metadata.get("scene_dna_candidate_selection")
    return deepcopy(selection) if isinstance(selection, dict) else None


def _additional_promoted_reference_paths(
    metadata: dict[str, Any] | None,
) -> list[Path]:
    if not isinstance(metadata, dict):
        return []
    bridge = metadata.get("bridge_metadata")
    bridge = bridge if isinstance(bridge, dict) else {}
    selection = bridge.get("scene_dna_candidate_selection")
    selection = selection if isinstance(selection, dict) else {}
    selected_path = str(bridge.get("reference_image_path") or "")
    result: list[Path] = []
    for raw in selection.get("promoted_reference_image_paths", []):
        path = Path(str(raw))
        if str(path) == selected_path or path in result or not path.is_file():
            continue
        result.append(path)
    return result


def _resolve_architecture_assets(
    brief: dict[str, Any],
    registry: AssetRegistry,
    asset_dir: Path,
    *,
    mode: str,
    scene_dna_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    architecture = brief.get("architecture")
    if not isinstance(architecture, dict):
        return []
    styles = list(brief.get("styles", []))
    results: list[dict[str, Any]] = []
    category_use_count: dict[str, int] = {}
    for collection_name, default_category in (("doors", "door"), ("windows", "window")):
        openings = architecture.get(collection_name, [])
        if not isinstance(openings, list):
            continue
        for opening in openings:
            if not isinstance(opening, dict):
                continue
            opening_id = str(opening.get("id") or default_category)
            policy = opening.get("asset_policy")
            policy = policy if isinstance(policy, dict) else {}
            policy_mode = str(policy.get("mode") or "prefer_library")
            category = str(policy.get("category") or default_category)
            fallback = str(policy.get("fallback") or "parametric")
            matched = None
            target_dimensions = {
                "width": float(opening.get("width", 1.0) or 1.0),
                "length": 0.08 if default_category == "door" else 0.10,
                "height": float(opening.get("height", 1.0) or 1.0),
            }
            dimension_policy = dimension_policy_for_category(category)
            dimension_rejections: list[dict[str, Any]] = []
            if policy_mode == "prefer_library":
                matched = registry.find(
                    category,
                    styles,
                    variant_index=category_use_count.get(category, 0),
                    target_dimensions=target_dimensions,
                    dimension_policy=dimension_policy,
                    rejections=dimension_rejections,
                    scene_dna_contract=scene_dna_contract,
                    object_id=opening_id,
                )
            if not matched:
                binding = {
                    "status": "parametric_fallback",
                    "category": category,
                    "fallback": fallback,
                    "reason": (
                        "approved_assets_dimension_incompatible"
                        if dimension_rejections
                        else "approved_asset_missing"
                    ),
                    "requested_dimensions": target_dimensions,
                    "dimension_policy": dimension_policy,
                    "dimension_rejections": dimension_rejections,
                }
                opening["asset_binding"] = binding
                results.append(
                    {
                        "opening_id": opening_id,
                        "category": category,
                        **binding,
                    }
                )
                continue

            category_use_count[category] = category_use_count.get(category, 0) + 1
            source = Path(str(matched["resolved_glb_path"]))
            staged_relative = Path("architecture") / f"{opening_id}.glb"
            destination = asset_dir / staged_relative
            if mode != "plan":
                _copy_asset(source, destination)
            binding: dict[str, Any] = {
                "status": "reused",
                "asset_id": str(matched.get("asset_id") or source.stem),
                "category": category,
                "source": str(source),
                "staged_relative": str(staged_relative),
                "fallback": fallback,
                "requested_dimensions": target_dimensions,
                "dimension_policy": deepcopy(
                    matched.get("_dimension_policy") or dimension_policy
                ),
                "dimension_resolution": deepcopy(
                    matched.get("_dimension_resolution")
                ),
            }
            if isinstance(matched.get("dimensions"), dict):
                binding["source_dimensions"] = dict(matched["dimensions"])
            for key in ORIENTATION_METADATA_KEYS:
                if key in matched:
                    binding[key] = matched[key]
            facing_plan = {
                "id": opening_id,
                "yaw": 0.0,
                "preferred_wall": str(opening.get("wall") or ""),
                "facing_constraint": {
                    "mode": "into_room",
                    "wall": str(opening.get("wall") or ""),
                    "contact_face": "back",
                    "local_front_fallback": "-y",
                },
                **{key: binding[key] for key in ORIENTATION_METADATA_KEYS if key in binding},
            }
            placement_yaw = solve_facing_yaw(facing_plan)
            if placement_yaw is not None:
                binding["placement_yaw_degrees"] = placement_yaw
            opening["asset_binding"] = binding
            results.append(
                {
                    "opening_id": opening_id,
                    "category": category,
                    "status": "reused",
                    "asset_id": binding["asset_id"],
                    "source": str(source),
                    "staged": str(destination) if mode != "plan" else None,
                    "placement_yaw_degrees": placement_yaw,
                    "dimension_resolution": binding["dimension_resolution"],
                    "scene_dna_score": deepcopy(
                        matched.get("_scene_dna_score")
                    ),
                }
            )
    return results


def generate_trellis_asset(
    obj: dict[str, Any],
    output_path: Path,
    *,
    trellis_url: str,
    seed: int,
    timeout: float,
    steps: int,
    texture_size: int,
    decimation_target: int,
    pipeline_type: str,
    preprocess_image: bool,
    reference_image_path: Path | None = None,
) -> dict[str, Any]:
    """Call the local Flux + TRELLIS.2 bridge and stage one GLB."""

    request_payload = {
        "input_text": str(obj["asset_prompt"]),
        "seed": seed,
        "pipeline_type": pipeline_type,
        "preprocess_image": preprocess_image,
        "sparse_steps": steps,
        "shape_steps": steps,
        "tex_steps": steps,
        "texture_size": texture_size,
        "decimation_target": decimation_target,
        "simplify_limit": 1_048_576,
    }
    generation_spec = obj.get("asset_generation_spec")
    generation_spec = generation_spec if isinstance(generation_spec, dict) else {}
    scene_dna = generation_spec.get("scene_dna")
    if isinstance(scene_dna, dict) and scene_dna.get("contract_hash"):
        request_payload["scene_dna"] = deepcopy(scene_dna)
        request_payload["scene_dna_candidate_count"] = int(
            scene_dna.get("candidate_funnel", {}).get(
                "isolated_2d_candidates", 1
            )
        )
    if reference_image_path is not None:
        request_payload["reference_image_path"] = str(reference_image_path.resolve())
    deadline = time.time() + timeout
    # A supervised bridge may recycle between completed candidate pairs to
    # keep its memory-pressure cgroup bounded.  Retry only failures that occur
    # before an HTTP response is received; once the server returns a job id we
    # never re-submit that request.
    while True:
        try:
            status, accepted = _post_json(
                trellis_url.rstrip("/") + "/generate",
                request_payload,
                timeout=min(30.0, timeout),
            )
            break
        except RETRYABLE:
            if time.time() >= deadline:
                raise
            time.sleep(1.0)
    if status != 202:
        raise RuntimeError(f"TRELLIS.2 bridge returned {status}: {accepted}")
    job_id = str(accepted["job_id"])
    while time.time() < deadline:
        try:
            status, body, content_type = _get(
                trellis_url.rstrip("/") + f"/job/{job_id}", timeout=60.0
            )
        except RETRYABLE:
            time.sleep(3.0)
            continue
        if status == 200:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(body)
            metadata: dict[str, Any] | None = None
            meta_status, meta_body, _ = _get(
                trellis_url.rstrip("/") + f"/job/{job_id}/metadata", timeout=60.0
            )
            if meta_status == 200:
                try:
                    metadata = json.loads(meta_body.decode("utf-8"))
                except Exception as exc:
                    metadata = {"parse_error": str(exc)}
            return {
                "job_id": job_id,
                "content_type": content_type,
                "request": request_payload,
                "bridge_metadata": metadata,
            }
        if status == 500:
            raise RuntimeError(body.decode("utf-8", errors="replace"))
        if status not in {202, 404, 410}:
            raise RuntimeError(f"TRELLIS.2 job {job_id} returned {status}: {body[:500]!r}")
        time.sleep(3.0)
    raise TimeoutError(f"TRELLIS.2 job {job_id} timed out for {obj['id']}")


def resolve_assets(
    brief: dict[str, Any],
    output_dir: Path,
    *,
    mode: str,
    manifest_path: Path | None,
    trellis_url: str,
    seed: int,
    timeout: float,
    steps: int,
    texture_size: int,
    decimation_target: int,
    pipeline_type: str,
    preprocess_image: bool,
    max_new_assets: int,
    scene_dna_mode: str = "relation_aware",
    blender_bin: Path | None = None,
    scene_dna_multiview: bool = True,
    scene_dna_multiview_resolution: int = 420,
    scene_dna_semantic_model: str | None = None,
    scene_dna_semantic_device: str = "cpu",
    resume_staged_assets: bool = False,
    trellis_model_fingerprint: str = "unfrozen-local-trellis-model",
    rmbg_model_fingerprint: str = "unfrozen-local-rmbg-model",
    generation_code_version: str = "unfrozen-scene-v2-code",
    require_generated_asset_admission: bool = False,
) -> dict[str, Any]:
    registry = AssetRegistry(manifest_path)
    registry.prefetch(
        [
            {"category": str(obj.get("category") or ""), "styles": list(brief.get("styles", []))}
            for obj in brief.get("objects", [])
            if isinstance(obj, dict) and obj.get("category")
        ]
    )
    multiview_semantic_scorer = (
        Siglip2SemanticScorer(
            scene_dna_semantic_model,
            device=scene_dna_semantic_device,
        )
        if scene_dna_semantic_model
        else None
    )
    asset_dir = output_dir / "assets_staged"
    resumed_assets: dict[str, dict[str, Any]] = {}
    if resume_staged_assets and asset_dir.is_dir():
        for metadata_path in sorted(asset_dir.glob("*.json")):
            glb_path = metadata_path.with_suffix(".glb")
            if not glb_path.is_file() or glb_path.stat().st_size <= 0:
                continue
            try:
                checkpoint = read_json(metadata_path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            checkpoint_object = checkpoint.get("object") if isinstance(checkpoint, dict) else None
            if not isinstance(checkpoint_object, dict):
                continue
            object_id = str(checkpoint_object.get("id") or "")
            category = str(checkpoint_object.get("category") or "")
            asset_id = str(checkpoint_object.get("asset_id") or "")
            dimension_resolution = checkpoint_object.get("dimension_resolution")
            if (
                object_id != metadata_path.stem
                or not category
                or not asset_id
                or not isinstance(dimension_resolution, dict)
                or not bool(dimension_resolution.get("accepted"))
            ):
                continue
            certificate = checkpoint.get("content_certificate")
            metadata_payload = {
                key: value
                for key, value in checkpoint.items()
                if key not in {"object", "content_certificate"}
            }
            upstream = {
                "generation_key": str(checkpoint_object.get("asset_generation_key") or ""),
                "object_hash": content_hash(checkpoint_object),
                "metadata_hash": content_hash(metadata_payload),
            }
            valid, _ = verify_artifact_certificate(
                certificate if isinstance(certificate, dict) else {},
                glb_path,
                upstream=upstream,
                rules={"kind": "generated_asset_checkpoint", "version": 1},
            )
            if not valid:
                continue
            resumed_assets[object_id] = {
                "path": glb_path,
                "checkpoint": checkpoint,
                "object": checkpoint_object,
            }
    results: list[dict[str, Any]] = []
    initial_anchors: list[dict[str, Any]] = []
    initial_anchor_ids: set[str] = set()
    initial_anchor_category_count: dict[str, int] = {}
    for obj in brief.get("objects", []):
        if not isinstance(obj, dict):
            continue
        category = str(obj.get("category") or "")
        requested_dimensions = deepcopy(
            obj.get("requested_dimensions") or obj.get("dimensions")
        )
        if not category or not isinstance(requested_dimensions, dict):
            continue
        anchor = registry.find(
            category,
            list(brief.get("styles", [])),
            variant_index=initial_anchor_category_count.get(category, 0),
            target_dimensions=requested_dimensions,
            dimension_policy=deepcopy(
                obj.get("dimension_policy")
                or dimension_policy_for_category(category)
            ),
        )
        if anchor is not None:
            initial_anchor_category_count[category] = (
                initial_anchor_category_count.get(category, 0) + 1
            )
            anchor_id = str(
                anchor.get("asset_id") or anchor.get("resolved_glb_path") or ""
            )
            if anchor_id not in initial_anchor_ids:
                initial_anchor_ids.add(anchor_id)
                initial_anchors.append(
                    {
                        "object_id": str(obj.get("id") or ""),
                        "category": category,
                        "asset": anchor,
                    }
                )
    scene_dna_contract = build_scene_dna_contract(
        brief,
        brief.get("architecture") if isinstance(brief.get("architecture"), dict) else None,
        initial_anchors,
        ablation_mode=scene_dna_mode,
    )
    selection_contract = (
        scene_dna_contract
        if scene_dna_contract["selection_policy"]["style_reranking_enabled"]
        else None
    )
    brief["scene_dna"] = deepcopy(scene_dna_contract)
    scene_dna_path = output_dir / "scene_dna_contract.json"
    write_json(scene_dna_path, scene_dna_contract)
    architecture_results = _resolve_architecture_assets(
        brief,
        registry,
        asset_dir,
        mode=mode,
        scene_dna_contract=selection_contract,
    )
    missing: list[dict[str, Any]] = []
    category_use_count: dict[str, int] = {}
    group_index = member_group_index(brief.get("instance_groups", []))
    selected_group_assets: dict[str, dict[str, Any]] = {}

    for obj in brief["objects"]:
        category = str(obj["category"])
        group_entry = group_index.get(str(obj["id"]))
        group = group_entry.get("group") if group_entry else None
        member = group_entry.get("member") if group_entry else None
        group_id = str(group.get("group_id") or "") if isinstance(group, dict) else ""
        handed_pair = requires_handed_pair(group if isinstance(group, dict) else None)
        desired_pair_role = member_handedness_role(
            member if isinstance(member, dict) else None
        )
        asset_contract = (
            group.get("asset_contract")
            if isinstance(group, dict) and isinstance(group.get("asset_contract"), dict)
            else {}
        )
        mirror_axis = str(asset_contract.get("mirror_axis") or "lateral")
        reflection_requested = False
        handedness_provenance = ""
        if group_id:
            obj["instance_group_id"] = group_id
            obj["instance_group_role"] = str(member.get("role") or "member")
        requested_dimensions = deepcopy(
            obj.get("requested_dimensions") or obj.get("dimensions")
        )
        dimension_policy = deepcopy(
            obj.get("dimension_policy") or dimension_policy_for_category(category)
        )
        dimension_rejections: list[dict[str, Any]] = []
        matched = None
        group_primary = selected_group_assets.get(group_id) if group_id else None
        if group_primary is not None:
            primary_asset = group_primary["asset"]
            primary_source_role = str(group_primary.get("source_pair_role") or "")
            family_id = str(primary_asset.get("asset_family_id") or "")
            if family_id and str(asset_contract.get("match_mode") or "") == "same_family":
                matched = registry.find(
                    category,
                    list(brief.get("styles", [])),
                    variant_index=category_use_count.get(category, 0),
                    target_dimensions=requested_dimensions,
                    dimension_policy=dimension_policy,
                    rejections=dimension_rejections,
                    family_id=family_id,
                    pair_role=desired_pair_role if handed_pair else None,
                    scene_dna_contract=selection_contract,
                    object_id=str(obj["id"]),
                )
                if matched is not None and handed_pair:
                    handedness_provenance = "manifest_pair_role"
            if (
                matched is None
                and str(asset_contract.get("fallback") or "same_asset_reuse")
                in {"same_asset_reuse", "mirror_primary"}
            ):
                matched = registry.find(
                    category,
                    list(brief.get("styles", [])),
                    target_dimensions=requested_dimensions,
                    dimension_policy=dimension_policy,
                    rejections=dimension_rejections,
                    asset_id=str(primary_asset.get("asset_id") or ""),
                    scene_dna_contract=selection_contract,
                    object_id=str(obj["id"]),
                )
                if matched is not None and handed_pair:
                    reflection_requested = bool(
                        desired_pair_role
                        and primary_source_role
                        and desired_pair_role != primary_source_role
                    )
                    handedness_provenance = (
                        "local_reflection_pair"
                        if reflection_requested
                        else "mirror_pair_primary"
                    )
        if matched is None:
            if handed_pair and desired_pair_role:
                matched = registry.find(
                    category,
                    list(brief.get("styles", [])),
                    variant_index=category_use_count.get(category, 0),
                    target_dimensions=requested_dimensions,
                    dimension_policy=dimension_policy,
                    rejections=dimension_rejections,
                    pair_role=desired_pair_role,
                    scene_dna_contract=selection_contract,
                    object_id=str(obj["id"]),
                )
                if matched is not None:
                    handedness_provenance = "manifest_pair_role"
            if matched is None:
                matched = registry.find(
                    category,
                    list(brief.get("styles", [])),
                    variant_index=category_use_count.get(category, 0),
                    target_dimensions=requested_dimensions,
                    dimension_policy=dimension_policy,
                    rejections=dimension_rejections,
                    scene_dna_contract=selection_contract,
                    object_id=str(obj["id"]),
                )
                if matched is not None and handed_pair:
                    source_role = str(matched.get("pair_role") or "")
                    reflection_requested = bool(
                        desired_pair_role
                        and source_role
                        and desired_pair_role != source_role
                    )
                    handedness_provenance = (
                        "local_reflection_pair"
                        if reflection_requested
                        else (
                            "mirror_pair_primary"
                            if source_role
                            else "source_pair_role_unverified"
                        )
                    )
        if matched:
            if group_id and group_id not in selected_group_assets:
                selected_group_assets[group_id] = {
                    "asset": deepcopy(matched),
                    "source_pair_role": str(matched.get("pair_role") or ""),
                }
            category_use_count[category] = category_use_count.get(category, 0) + 1
            source = Path(str(matched["resolved_glb_path"]))
            destination = asset_dir / f"{obj['id']}.glb"
            if mode != "plan":
                _copy_asset(source, destination)
            resolution = deepcopy(matched["_dimension_resolution"])
            obj["requested_dimensions"] = requested_dimensions
            obj["source_dimensions"] = resolution.get("source_dimensions")
            obj["dimension_policy"] = deepcopy(matched["_dimension_policy"])
            obj["dimension_resolution"] = resolution
            obj["dimensions"] = {
                key: float(resolution["effective_dimensions"][key]) for key in AXES
            }
            for key in ORIENTATION_METADATA_KEYS:
                if key in matched:
                    obj[key] = matched[key]
            if "included_components" in matched:
                obj["included_components"] = deepcopy(matched["included_components"])
            obj["asset_id"] = str(matched.get("asset_id") or source.stem)
            obj["asset_source"] = "curated_library"
            obj["asset_lifecycle_status"] = str(
                matched.get("lifecycle_status") or "curated"
            )
            obj["scene_dna_score"] = deepcopy(matched.get("_scene_dna_score"))
            if matched.get("asset_family_id"):
                obj["asset_family_id"] = str(matched["asset_family_id"])
            if group_id:
                primary_asset = selected_group_assets[group_id]["asset"]
                if handed_pair:
                    family_key = str(
                        primary_asset.get("asset_family_id")
                        or f"mirror_pair:{primary_asset.get('asset_id') or source.stem}"
                    )
                else:
                    family_key = str(
                        matched.get("asset_family_id")
                        or f"same_asset:{matched.get('asset_id') or source.stem}"
                    )
                obj["instance_group_asset_family"] = family_key
                if handed_pair:
                    obj["asset_pair_role"] = desired_pair_role
                    source_pair_role = str(matched.get("pair_role") or "")
                    if source_pair_role:
                        obj["asset_source_pair_role"] = source_pair_role
                    else:
                        obj.pop("asset_source_pair_role", None)
                    if matched.get("pair_role_semantics"):
                        obj["asset_pair_role_semantics"] = str(
                            matched["pair_role_semantics"]
                        )
                    if isinstance(matched.get("pair_role_qa"), dict):
                        obj["asset_pair_role_qa"] = deepcopy(
                            matched["pair_role_qa"]
                        )
                    obj["asset_handedness_provenance"] = handedness_provenance
                    if reflection_requested:
                        obj["asset_reflection_axis"] = (
                            _resolved_handedness_reflection_axis(
                                mirror_axis, primary_asset
                            )
                        )
                        obj["asset_reflection_space"] = "canonical_asset_local"
                        obj["asset_reflection_source_asset_id"] = str(
                            primary_asset.get("asset_id") or source.stem
                        )
                        obj["instance_group_asset_strategy"] = (
                            "local_mirror_fallback"
                        )
                    else:
                        obj.pop("asset_reflection_axis", None)
                        obj.pop("asset_reflection_space", None)
                        obj.pop("asset_reflection_source_asset_id", None)
                        obj["instance_group_asset_strategy"] = (
                            "manifest_pair_role"
                            if handedness_provenance == "manifest_pair_role"
                            else "mirror_pair_primary"
                        )
                else:
                    obj["instance_group_asset_strategy"] = (
                        "manifest_family"
                        if matched.get("asset_family_id")
                        else "same_asset_reuse_fallback"
                    )
                    if matched.get("pair_role"):
                        obj["asset_pair_role"] = str(matched["pair_role"])
            results.append(
                {
                    "object_id": obj["id"],
                    "category": obj["category"],
                    "status": "reused",
                    "asset_id": obj["asset_id"],
                    "asset_lifecycle_status": obj["asset_lifecycle_status"],
                    "source": str(source),
                    "staged": str(destination) if mode != "plan" else None,
                    "requested_dimensions": requested_dimensions,
                    "source_dimensions": resolution.get("source_dimensions"),
                    "effective_dimensions": resolution.get("effective_dimensions"),
                    "scale_factors": resolution.get("scale_factors"),
                    "dimension_policy": obj["dimension_policy"],
                    "dimension_resolution": resolution,
                    "instance_group_id": group_id or None,
                    "instance_group_role": obj.get("instance_group_role"),
                    "instance_group_asset_family": obj.get(
                        "instance_group_asset_family"
                    ),
                    "instance_group_asset_strategy": obj.get(
                        "instance_group_asset_strategy"
                    ),
                    "asset_pair_role": obj.get("asset_pair_role"),
                    "asset_source_pair_role": obj.get(
                        "asset_source_pair_role"
                    ),
                    "asset_pair_role_semantics": obj.get(
                        "asset_pair_role_semantics"
                    ),
                    "asset_medial_axis": deepcopy(obj.get("asset_medial_axis")),
                    "asset_handedness_provenance": obj.get(
                        "asset_handedness_provenance"
                    ),
                    "asset_reflection_axis": obj.get("asset_reflection_axis"),
                    "scene_dna_score": deepcopy(obj.get("scene_dna_score")),
                }
            )
        else:
            obj["requested_dimensions"] = requested_dimensions
            obj["dimension_policy"] = dimension_policy
            obj["asset_dimension_rejections"] = dimension_rejections
            missing.append(obj)

    if mode == "reuse" and missing:
        incompatible_ids = [
            str(obj["id"]) for obj in missing if obj.get("asset_dimension_rejections")
        ]
        raise FileNotFoundError(
            "Curated asset library is missing compatible required categories: "
            + ", ".join(sorted({str(obj['category']) for obj in missing}))
            + (f"; dimension-incompatible objects: {', '.join(incompatible_ids)}" if incompatible_ids else "")
        )
    generation_units: dict[str, str] = {}
    generation_plan_entries: list[dict[str, Any]] = []
    for obj in missing:
        spec = build_asset_generation_spec(
            obj,
            list(brief.get("styles", [])),
            str(brief.get("original_prompt") or ""),
        )
        spec = apply_scene_dna_to_generation_spec(
            spec,
            scene_dna_contract,
            str(obj["id"]),
        )
        prompt = render_asset_prompt(spec)
        generation_contract = build_generation_contract(
            category=str(obj["category"]),
            prompt=prompt,
            target_dimensions_m=spec["target_dimensions_m"],
            seed=int(seed),
            model_fingerprint=trellis_model_fingerprint,
            rmbg_fingerprint=rmbg_model_fingerprint,
            pipeline_type=pipeline_type,
            steps=steps,
            texture_size=texture_size,
            decimation_target=decimation_target,
            preprocess_image=preprocess_image,
            code_version=generation_code_version,
        )
        generation_key = str(generation_contract["content_key"])
        reuse_from = generation_units.get(generation_key)
        if reuse_from is None:
            generation_units[generation_key] = str(obj["id"])
        obj["asset_generation_spec"] = spec
        obj["asset_prompt"] = prompt
        obj["asset_generation_key"] = generation_key
        obj["asset_generation_contract"] = generation_contract
        obj["missing_asset_subflow_contract"] = build_missing_asset_subflow_contract(
            spec, generation_contract
        )
        obj["asset_generation_strategy"] = (
            "generate_unique_asset" if reuse_from is None else "reuse_generated_asset"
        )
        obj["asset_generation_reuse_from"] = reuse_from
        group_entry = group_index.get(str(obj["id"]))
        if group_entry:
            obj["instance_group_asset_family"] = f"generation:{generation_key}"
            obj["instance_group_asset_strategy"] = (
                "shared_generation_spec"
                if reuse_from is not None
                else "group_generation_primary"
            )
        generation_plan_entries.append(
            {
                "object_id": str(obj["id"]),
                "category": str(obj["category"]),
                "required": bool(obj.get("required", True)),
                "provenance": str(obj.get("provenance") or "unspecified"),
                "requested_dimensions": deepcopy(obj["requested_dimensions"]),
                "generation_key": generation_key,
                "generation_contract": deepcopy(generation_contract),
                "missing_asset_subflow_contract": deepcopy(
                    obj["missing_asset_subflow_contract"]
                ),
                "strategy": obj["asset_generation_strategy"],
                "reuse_from_object_id": reuse_from,
                "asset_generation_spec": deepcopy(spec),
                "bridge_input_prompt": prompt,
                "final_flux_prompt": None,
                "prompt_metrics": {
                    "characters": len(prompt),
                    "words": len(prompt.split()),
                },
                "scene_dna_contract_hash": scene_dna_contract["contract_hash"],
                "candidate_funnel": deepcopy(
                    scene_dna_contract["generation_policy"]
                ),
                "post_generation_acceptance": {
                    "hard_geometry_and_capability_gate": "required",
                    "multiview_style_evaluation": "required",
                    "current_status": "not_generated",
                },
            }
        )

    missing_by_id = {str(obj["id"]): obj for obj in missing}
    for group in brief.get("instance_groups", []):
        if not requires_handed_pair(group if isinstance(group, dict) else None):
            continue
        member_rows = [
            member
            for member in group.get("members", [])
            if isinstance(member, dict)
            and str(member.get("object_id") or "") in missing_by_id
        ]
        if len(member_rows) != int(group.get("cardinality", 0) or 0):
            continue
        primary_member = member_rows[0]
        primary = missing_by_id[str(primary_member["object_id"])]
        primary_role = member_handedness_role(primary_member)
        mirror_axis = str(
            group.get("asset_contract", {}).get("mirror_axis") or "lateral"
        )
        resolved_mirror_axis = _resolved_handedness_reflection_axis(
            mirror_axis, primary
        )
        family_key = f"generation_mirror_pair:{primary['asset_generation_key']}"
        for member in member_rows:
            obj = missing_by_id[str(member["object_id"])]
            desired_role = member_handedness_role(member)
            obj["asset_pair_role"] = desired_role
            obj["instance_group_asset_family"] = family_key
            if desired_role != primary_role:
                obj["asset_generation_key"] = str(primary["asset_generation_key"])
                obj["asset_generation_strategy"] = "reuse_generated_asset"
                obj["asset_generation_reuse_from"] = str(primary["id"])
                obj["asset_reflection_axis"] = resolved_mirror_axis
                obj["asset_reflection_space"] = "canonical_asset_local"
                obj["asset_reflection_source_object_id"] = str(primary["id"])
                obj["asset_handedness_provenance"] = "local_reflection_pair"
                obj["instance_group_asset_strategy"] = "local_mirror_fallback"
            else:
                obj["asset_handedness_provenance"] = "mirror_pair_primary"
                obj["instance_group_asset_strategy"] = "mirror_pair_primary"

    generation_units = {}
    for obj in missing:
        generation_key = str(obj["asset_generation_key"])
        generation_units.setdefault(generation_key, str(obj["id"]))
    generation_entry_by_id = {
        str(entry["object_id"]): entry for entry in generation_plan_entries
    }
    for obj in missing:
        entry = generation_entry_by_id[str(obj["id"])]
        entry["generation_key"] = str(obj["asset_generation_key"])
        entry["strategy"] = str(obj["asset_generation_strategy"])
        entry["reuse_from_object_id"] = obj.get("asset_generation_reuse_from")

    current_generation_keys = {
        str(obj["id"]): str(obj["asset_generation_key"]) for obj in missing
    }
    resumed_assets = {
        object_id: checkpoint
        for object_id, checkpoint in resumed_assets.items()
        if current_generation_keys.get(object_id)
        == str(checkpoint["object"].get("asset_generation_key") or "")
    }

    resumable_generation_keys = {
        str(obj.get("asset_generation_key") or "")
        for obj in missing
        if str(obj.get("id") or "") in resumed_assets
    }
    resumable_generation_keys.discard("")
    unique_generation_count = len(generation_units)
    pending_unique_generation_count = len(
        set(generation_units).difference(resumable_generation_keys)
    )
    generation_plan_path = output_dir / "missing_asset_generation_plan.json"
    write_json(
        generation_plan_path,
        {
            "schema": "codex_trellis_missing_asset_generation_plan_v1",
            "source_scene_prompt": str(brief.get("original_prompt") or ""),
            "source_scene_prompt_path": str(output_dir / "selected_prompt.txt"),
            "required_asset_inventory": deepcopy(brief.get("asset_inventory", [])),
            "missing_instance_count": len(missing),
            "unique_generation_count": unique_generation_count,
            "resumed_generation_count": len(resumable_generation_keys),
            "pending_unique_generation_count": pending_unique_generation_count,
            "scene_dna_contract": str(scene_dna_path),
            "scene_dna_contract_hash": scene_dna_contract["contract_hash"],
            "candidate_funnel": deepcopy(scene_dna_contract["generation_policy"]),
            "generation_entries": generation_plan_entries,
        },
    )

    if mode == "trellis2" and pending_unique_generation_count > max_new_assets:
        raise RuntimeError(
            f"Refusing to generate {pending_unique_generation_count} unique new assets for "
            f"{len(missing)} missing instances; --max-new-assets={max_new_assets}"
        )
    health = None
    if mode == "trellis2" and pending_unique_generation_count:
        health = bridge_health(trellis_url)
        if not health.get("ok"):
            raise RuntimeError(f"TRELLIS.2 bridge is not healthy at {trellis_url}: {health}")

    generated_units: dict[str, dict[str, Any]] = {}
    generation_call_index = 0
    trellis_generation_attempt_count = 0
    resumed_instance_count = 0
    for obj in missing:
        destination = asset_dir / f"{obj['id']}.glb"
        requested_dimensions = deepcopy(obj["requested_dimensions"])
        if mode == "trellis2":
            generation_key = str(obj["asset_generation_key"])
            generated = generated_units.get(generation_key)
            checkpoint = resumed_assets.get(str(obj.get("id") or ""))
            # Prefer an object's own complete checkpoint even when an earlier
            # member of the same generation family already populated the
            # in-memory reuse map. This preserves per-instance asset metadata
            # for interrupted paired/grouped generations.
            if checkpoint is not None:
                checkpoint_object = checkpoint["object"]
                if (
                    str(checkpoint_object.get("category") or "") != str(obj["category"])
                    or str(checkpoint_object.get("asset_generation_key") or "")
                    != generation_key
                ):
                    checkpoint = None
            if checkpoint is not None:
                checkpoint_object = deepcopy(checkpoint["object"])
                obj.update(checkpoint_object)
                saved_payload = checkpoint["checkpoint"]
                metadata = {
                    key: deepcopy(value)
                    for key, value in saved_payload.items()
                    if key != "object"
                }
                generated = {
                    "path": Path(checkpoint["path"]),
                    "asset_id": str(obj.get("asset_id") or f"resumed_{obj['id']}"),
                    "object_id": str(obj["id"]),
                    "metadata": metadata,
                    "final_flux_prompt": obj.get("final_flux_prompt"),
                    "scene_dna_2d_candidate_selection": deepcopy(
                        obj.get("scene_dna_2d_candidate_selection")
                    ),
                    "scene_dna_multiview": deepcopy(obj.get("scene_dna_multiview")),
                    "scene_dna_harmonization": deepcopy(
                        obj.get("scene_dna_harmonization")
                    ),
                    "generation_runtime_key": obj.get("asset_generation_runtime_key"),
                    "generation_runtime_contract": deepcopy(
                        obj.get("asset_generation_runtime_contract")
                    ),
                }
                generated_units[generation_key] = generated
                resumed_instance_count += 1
            if generated is None:
                can_evaluate_multiview = bool(
                    scene_dna_multiview
                    and blender_bin is not None
                    and Path(blender_bin).is_file()
                )
                loop_limit = int(
                    scene_dna_contract.get("generation_policy", {}).get(
                        "max_harmonization_loops", 0
                    )
                ) if can_evaluate_multiview else 0
                attempt_records: list[dict[str, Any]] = []
                candidate_root = (
                    output_dir
                    / "scene_dna_generation_candidates"
                    / str(obj["id"])
                )
                persisted_candidate_records = load_candidate_checkpoints(
                    candidate_root,
                    obj,
                    str(scene_dna_contract.get("contract_hash") or ""),
                )
                resumed_candidate_count = 0
                for harmonization_attempt in range(loop_limit + 1):
                    candidate_asset_dir = candidate_root / f"attempt_{harmonization_attempt:02d}" / "assets"
                    candidate_path = candidate_asset_dir / f"{obj['id']}.glb"
                    candidate_key = (harmonization_attempt, 1)
                    candidate_record = persisted_candidate_records.get(candidate_key)
                    if candidate_record is not None:
                        candidate_metadata = deepcopy(candidate_record["metadata"])
                        candidate_seed = int(candidate_record["seed"])
                        multiview_report = deepcopy(candidate_record.get("multiview"))
                        resumed_candidate_count += 1
                    else:
                        candidate_metadata = generate_trellis_asset(
                            obj,
                            candidate_path,
                            trellis_url=trellis_url,
                            seed=seed + trellis_generation_attempt_count,
                            timeout=timeout,
                            steps=steps,
                            texture_size=texture_size,
                            decimation_target=decimation_target,
                            pipeline_type=pipeline_type,
                            preprocess_image=preprocess_image,
                        )
                        candidate_seed = seed + trellis_generation_attempt_count
                        multiview_report: dict[str, Any] | None = None
                        if can_evaluate_multiview:
                            bridge_metadata = candidate_metadata.get("bridge_metadata")
                            bridge_metadata = (
                                bridge_metadata if isinstance(bridge_metadata, dict) else {}
                            )
                            reference_value = bridge_metadata.get("reference_image_path")
                            reference_path = Path(str(reference_value)) if reference_value else None
                            try:
                                multiview_report = render_and_evaluate_generated_asset(
                                    blender_bin=Path(blender_bin),
                                    asset_dir=candidate_asset_dir,
                                    output_dir=(
                                        candidate_root
                                        / f"attempt_{harmonization_attempt:02d}"
                                        / "multiview"
                                    ),
                                    obj=obj,
                                    contract=scene_dna_contract,
                                    reference_image_path=reference_path,
                                    resolution=scene_dna_multiview_resolution,
                                    semantic_scorer=multiview_semantic_scorer,
                                )
                            except Exception as exc:
                                multiview_report = {
                                    "schema": "scene_dna_generated_asset_multiview_v1",
                                    "object_id": str(obj["id"]),
                                    "category": str(obj["category"]),
                                    "scene_dna_contract_hash": scene_dna_contract.get(
                                        "contract_hash"
                                    ),
                                    "evaluated": False,
                                    "automated_pixel_multiview_pass": False,
                                    "acceptance": "evaluation_error_style_review_required",
                                    "error": f"{type(exc).__name__}: {exc}",
                                    "semantic_embedding_evaluated": False,
                                }
                        candidate_record = {
                            "attempt": harmonization_attempt,
                            "candidate_rank": 1,
                            "seed": candidate_seed,
                            "path": str(candidate_path),
                            "metadata": candidate_metadata,
                            "multiview": multiview_report,
                        }
                        persist_candidate_checkpoint(
                            candidate_root,
                            obj,
                            str(scene_dna_contract.get("contract_hash") or ""),
                            candidate_record,
                        )
                    trellis_generation_attempt_count += 1
                    attempt_records.append(deepcopy(candidate_record))
                    promoted_paths = _additional_promoted_reference_paths(
                        candidate_metadata
                    )
                    for promoted_index, promoted_reference_path in enumerate(
                        promoted_paths, start=2
                    ):
                        promoted_root = (
                            candidate_root
                            / f"attempt_{harmonization_attempt:02d}_candidate_{promoted_index:02d}"
                        )
                        promoted_asset_dir = promoted_root / "assets"
                        promoted_path = promoted_asset_dir / f"{obj['id']}.glb"
                        promoted_key = (harmonization_attempt, promoted_index)
                        promoted_record = persisted_candidate_records.get(promoted_key)
                        if promoted_record is not None:
                            resumed_candidate_count += 1
                        else:
                            promoted_metadata = generate_trellis_asset(
                                obj,
                                promoted_path,
                                trellis_url=trellis_url,
                                seed=candidate_seed,
                                timeout=timeout,
                                steps=steps,
                                texture_size=texture_size,
                                decimation_target=decimation_target,
                                pipeline_type=pipeline_type,
                                preprocess_image=preprocess_image,
                                reference_image_path=promoted_reference_path,
                            )
                            promoted_multiview: dict[str, Any] | None = None
                            if can_evaluate_multiview:
                                try:
                                    promoted_multiview = render_and_evaluate_generated_asset(
                                        blender_bin=Path(blender_bin),
                                        asset_dir=promoted_asset_dir,
                                        output_dir=promoted_root / "multiview",
                                        obj=obj,
                                        contract=scene_dna_contract,
                                        reference_image_path=promoted_reference_path,
                                        resolution=scene_dna_multiview_resolution,
                                        semantic_scorer=multiview_semantic_scorer,
                                    )
                                except Exception as exc:
                                    promoted_multiview = {
                                        "schema": "scene_dna_generated_asset_multiview_v1",
                                        "object_id": str(obj["id"]),
                                        "category": str(obj["category"]),
                                        "scene_dna_contract_hash": scene_dna_contract.get(
                                            "contract_hash"
                                        ),
                                        "evaluated": False,
                                        "automated_pixel_multiview_pass": False,
                                        "acceptance": "evaluation_error_style_review_required",
                                        "error": f"{type(exc).__name__}: {exc}",
                                        "semantic_embedding_evaluated": False,
                                    }
                            promoted_record = {
                                "attempt": harmonization_attempt,
                                "candidate_rank": promoted_index,
                                "seed": candidate_seed,
                                "reference_image_path": str(
                                    promoted_reference_path
                                ),
                                "path": str(promoted_path),
                                "metadata": promoted_metadata,
                                "multiview": promoted_multiview,
                            }
                            persist_candidate_checkpoint(
                                candidate_root,
                                obj,
                                str(scene_dna_contract.get("contract_hash") or ""),
                                promoted_record,
                            )
                        trellis_generation_attempt_count += 1
                        attempt_records.append(deepcopy(promoted_record))
                    current_batch = [
                        item
                        for item in attempt_records
                        if int(item["attempt"]) == harmonization_attempt
                    ]
                    if any(
                        isinstance(item.get("multiview"), dict)
                        and bool(
                            item["multiview"].get(
                                "automated_pixel_multiview_pass"
                            )
                        )
                        for item in current_batch
                    ):
                        break
                    if not can_evaluate_multiview:
                        break
                selected_attempt, feasibility_decision = select_3d_candidate(
                    attempt_records,
                    require_hard_geometry=can_evaluate_multiview,
                )
                write_json(
                    candidate_root / "scene_dna_3d_candidate_selection.json",
                    feasibility_decision,
                )
                if not bool(feasibility_decision["usable_for_scene_assembly"]):
                    raise RuntimeError(
                        "All generated SceneDNA candidates failed the generic 3D "
                        "feasibility gate; refusing to assemble a best-of-failures asset. "
                        f"See {candidate_root / 'scene_dna_3d_candidate_selection.json'}"
                    )
                _copy_asset(Path(str(selected_attempt["path"])), destination)
                metadata = deepcopy(selected_attempt["metadata"])
                runtime_upstream, _ = _candidate_certificate_inputs(
                    obj,
                    str(scene_dna_contract.get("contract_hash") or ""),
                    selected_attempt,
                )
                obj["asset_generation_runtime_contract"] = deepcopy(
                    runtime_upstream["generation_contract"]
                )
                obj["asset_generation_runtime_key"] = str(
                    runtime_upstream["generation_key"]
                )
                obj["scene_dna_multiview"] = deepcopy(selected_attempt.get("multiview"))
                obj["scene_dna_harmonization"] = {
                    "schema": "scene_dna_harmonization_loop_v1",
                    "maximum_regeneration_loops": loop_limit,
                    "generation_attempt_count": len(attempt_records),
                    "resumed_candidate_count": resumed_candidate_count,
                    "selected_attempt": int(selected_attempt["attempt"]),
                    "selected_candidate_rank": int(
                        selected_attempt.get("candidate_rank", 1)
                    ),
                    "feasibility_decision": deepcopy(feasibility_decision),
                    "stopped_after_automated_pass": bool(
                        (selected_attempt.get("multiview") or {}).get(
                            "automated_pixel_multiview_pass"
                        )
                    ),
                    "attempts": [
                        {
                            "attempt": int(item["attempt"]),
                            "candidate_rank": int(item.get("candidate_rank", 1)),
                            "seed": int(item["seed"]),
                            "reference_image_path": item.get(
                                "reference_image_path"
                            ),
                            "path": str(item["path"]),
                            "job_id": str(item["metadata"].get("job_id") or ""),
                            "multiview_report": deepcopy(item.get("multiview")),
                        }
                        for item in attempt_records
                    ],
                }
                generation_call_index += 1
                obj["asset_id"] = f"generated_{obj['id']}_{metadata['job_id']}"
                obj["asset_source"] = "trellis2_staging"
                obj["asset_lifecycle_status"] = "generated_for_run"
                obj["temporary_admission_status"] = "required_before_production_assembly"
                generated_units[generation_key] = {
                    "path": destination,
                    "asset_id": obj["asset_id"],
                    "object_id": str(obj["id"]),
                    "metadata": metadata,
                    "final_flux_prompt": _final_flux_prompt(metadata),
                    "scene_dna_2d_candidate_selection": (
                        _scene_dna_candidate_selection(metadata)
                    ),
                    "scene_dna_multiview": deepcopy(
                        obj.get("scene_dna_multiview")
                    ),
                    "scene_dna_harmonization": deepcopy(
                        obj.get("scene_dna_harmonization")
                    ),
                    "generation_runtime_key": obj.get("asset_generation_runtime_key"),
                    "generation_runtime_contract": deepcopy(
                        obj.get("asset_generation_runtime_contract")
                    ),
                }
            elif checkpoint is None:
                _copy_asset(Path(generated["path"]), destination)
                obj["asset_id"] = str(generated["asset_id"])
                obj["asset_source"] = "trellis2_generated_instance_reuse"
                metadata = {
                    "generation_reuse": {
                        "generation_key": generation_key,
                        "source_object_id": generated["object_id"],
                        "source_path": str(generated["path"]),
                    },
                    "primary_generation_metadata": deepcopy(generated["metadata"]),
                }
                obj["scene_dna_multiview"] = deepcopy(
                    generated.get("scene_dna_multiview")
                )
                obj["scene_dna_harmonization"] = deepcopy(
                    generated.get("scene_dna_harmonization")
                )
                obj["asset_generation_runtime_key"] = generated.get(
                    "generation_runtime_key"
                )
                obj["asset_generation_runtime_contract"] = deepcopy(
                    generated.get("generation_runtime_contract")
                )
            obj["final_flux_prompt"] = (
                _final_flux_prompt(metadata)
                if generated is None
                else str(generated.get("final_flux_prompt") or "") or None
            )
            obj["scene_dna_2d_candidate_selection"] = (
                _scene_dna_candidate_selection(metadata)
                if generated is None
                else deepcopy(
                    generated.get("scene_dna_2d_candidate_selection")
                )
            )
            obj["source_dimensions"] = None
            obj["dimensions"] = deepcopy(requested_dimensions)
            obj["dimension_resolution"] = {
                "accepted": True,
                "status": "generated_to_requested_dimensions",
                "policy_mode": str(obj["dimension_policy"].get("mode")),
                "requested_dimensions": requested_dimensions,
                "source_dimensions": None,
                "effective_dimensions": deepcopy(requested_dimensions),
                "scale_factors": None,
                "max_requested_error": 0.0,
                "requires_runtime_bounds_check": True,
                "reason": "TRELLIS.2 asset generated for the requested physical dimensions",
            }
            checkpoint_payload = {"object": obj, **metadata}
            metadata_payload = {
                key: value for key, value in checkpoint_payload.items() if key != "object"
            }
            checkpoint_payload["content_certificate"] = make_artifact_certificate(
                destination,
                upstream={
                    "generation_key": generation_key,
                    "object_hash": content_hash(obj),
                    "metadata_hash": content_hash(metadata_payload),
                },
                rules={"kind": "generated_asset_checkpoint", "version": 1},
            )
            write_json(asset_dir / f"{obj['id']}.json", checkpoint_payload)
            status = "generated"
        else:
            obj["asset_id"] = f"planned_{obj['category']}"
            obj["asset_source"] = "missing_generation_plan"
            obj["asset_lifecycle_status"] = "generated_for_run"
            metadata = None
            status = "planned_missing"
            obj["source_dimensions"] = None
            obj["dimensions"] = deepcopy(requested_dimensions)
            obj["dimension_resolution"] = {
                "accepted": True,
                "status": "planned_generation_for_requested_dimensions",
                "policy_mode": str(obj["dimension_policy"].get("mode")),
                "requested_dimensions": requested_dimensions,
                "source_dimensions": None,
                "effective_dimensions": deepcopy(requested_dimensions),
                "scale_factors": None,
                "max_requested_error": 0.0,
                "requires_runtime_bounds_check": True,
                "reason": "no compatible curated asset; plan generation at requested dimensions",
            }
        results.append(
            {
                "object_id": obj["id"],
                "category": obj["category"],
                "status": status,
                "asset_id": obj["asset_id"],
                "staged": str(destination) if mode == "trellis2" else None,
                "metadata": metadata,
                "requested_dimensions": requested_dimensions,
                "source_dimensions": None,
                "effective_dimensions": obj["dimension_resolution"]["effective_dimensions"],
                "scale_factors": None,
                "dimension_policy": obj["dimension_policy"],
                "dimension_resolution": obj["dimension_resolution"],
                "dimension_rejections": obj.get("asset_dimension_rejections", []),
                "generation_key": obj.get("asset_generation_key"),
                "generation_contract": deepcopy(obj.get("asset_generation_contract")),
                "generation_runtime_key": obj.get("asset_generation_runtime_key"),
                "generation_runtime_contract": deepcopy(
                    obj.get("asset_generation_runtime_contract")
                ),
                "generation_strategy": obj.get("asset_generation_strategy"),
                "generation_reuse_from": obj.get("asset_generation_reuse_from"),
                "asset_generation_spec": deepcopy(obj.get("asset_generation_spec")),
                "missing_asset_subflow_contract": deepcopy(
                    obj.get("missing_asset_subflow_contract")
                ),
                "asset_lifecycle_status": obj.get("asset_lifecycle_status"),
                "temporary_admission_status": obj.get(
                    "temporary_admission_status"
                ),
                "bridge_input_prompt": obj.get("asset_prompt"),
                "final_flux_prompt": obj.get("final_flux_prompt"),
                "scene_dna_2d_candidate_selection": deepcopy(
                    obj.get("scene_dna_2d_candidate_selection")
                ),
                "scene_dna_multiview": deepcopy(
                    obj.get("scene_dna_multiview")
                ),
                "scene_dna_harmonization": deepcopy(
                    obj.get("scene_dna_harmonization")
                ),
                "instance_group_id": obj.get("instance_group_id"),
                "instance_group_role": obj.get("instance_group_role"),
                "instance_group_asset_family": obj.get(
                    "instance_group_asset_family"
                ),
                "instance_group_asset_strategy": obj.get(
                    "instance_group_asset_strategy"
                ),
                "asset_pair_role": obj.get("asset_pair_role"),
                "asset_source_pair_role": obj.get("asset_source_pair_role"),
                "asset_pair_role_semantics": obj.get(
                    "asset_pair_role_semantics"
                ),
                "asset_medial_axis": deepcopy(obj.get("asset_medial_axis")),
                "asset_handedness_provenance": obj.get(
                    "asset_handedness_provenance"
                ),
                "asset_reflection_axis": obj.get("asset_reflection_axis"),
            }
        )

    component_resolution = finalize_integrated_component_resolution(brief)
    blocking_component_statuses = {
        "asset_manifest_component_shortfall",
        "parent_missing_after_asset_resolution",
    }
    component_resolution_ok = not any(
        isinstance(item, dict)
        and str(item.get("resolution_status")) in blocking_component_statuses
        for item in component_resolution
    )
    harmony_certificate = build_harmony_certificate(
        scene_dna_contract,
        results,
    )
    harmony_certificate_path = output_dir / "generated_asset_harmony_certificate.json"
    write_json(harmony_certificate_path, harmony_certificate)
    report = {
        "schema": "codex_trellis_asset_resolution_v2",
        "mode": mode,
        "manifest": str(manifest_path.resolve()) if manifest_path else None,
        "asset_index": {
            "enabled": registry.index is not None,
            "path": str(registry.index.path) if registry.index is not None else None,
            "index_version": registry.index.index_version if registry.index is not None else None,
            "batch_prefetch": deepcopy(registry.batch_prefetch_report),
            "queries": deepcopy(registry.index_queries),
            "deterministic_hard_filter_ann_rerank": registry.index is not None,
        },
        "asset_dir": str(asset_dir),
        "missing_asset_generation_plan": str(generation_plan_path),
        "scene_dna_contract": str(scene_dna_path),
        "scene_dna_mode": scene_dna_mode,
        "scene_dna_contract_hash": scene_dna_contract["contract_hash"],
        "harmony_certificate": str(harmony_certificate_path),
        "harmony_certificate_hash": harmony_certificate["certificate_hash"],
        "style_review_required": bool(
            harmony_certificate["style_review_required"]
        ),
        "bridge_health": health,
        "results": results,
        "architecture_results": architecture_results,
        "component_resolution": deepcopy(component_resolution),
        "component_resolution_ok": component_resolution_ok,
        "missing_count": sum(1 for item in results if item["status"] == "planned_missing"),
        "generated_count": sum(1 for item in results if item["status"] == "generated"),
        "generated_for_run_count": sum(
            1
            for item in results
            if item.get("asset_lifecycle_status") == "generated_for_run"
        ),
        "unique_generated_count": generation_call_index,
        "resumed_generated_instance_count": resumed_instance_count,
        "resumed_generation_key_count": len(resumable_generation_keys),
        "pending_unique_generation_count_at_resume": pending_unique_generation_count,
        "trellis_generation_attempt_count": trellis_generation_attempt_count,
        "unique_generation_planned_count": unique_generation_count,
        "reused_count": sum(1 for item in results if item["status"] == "reused"),
        "architecture_reused_count": sum(
            1 for item in architecture_results if item["status"] == "reused"
        ),
        "architecture_fallback_count": sum(
            1
            for item in architecture_results
            if item["status"] == "parametric_fallback"
        ),
        "generated_asset_admission_required": bool(
            require_generated_asset_admission
        ),
        "generated_asset_admission_complete": not any(
            item.get("status") == "generated"
            and item.get("asset_lifecycle_status") != "scene_specific_approved"
            for item in results
        ),
        "ready_for_assembly": component_resolution_ok
        and all(item["status"] in {"generated", "reused"} for item in results)
        and (
            not require_generated_asset_admission
            or not any(
                item.get("status") == "generated"
                and item.get("asset_lifecycle_status")
                != "scene_specific_approved"
                for item in results
            )
        ),
        "dimension_resolution": {
            "accepted_count": sum(
                1
                for item in results
                if item.get("dimension_resolution", {}).get("accepted")
            ),
            "scaled_count": sum(
                1
                for item in results
                if item.get("dimension_resolution", {}).get("status")
                in {"bounded_uniform_scale", "bounded_axis_scale"}
            ),
            "generated_or_planned_count": sum(
                1
                for item in results
                if item.get("dimension_resolution", {}).get("status")
                in {
                    "generated_to_requested_dimensions",
                    "planned_generation_for_requested_dimensions",
                }
            ),
            "incompatible_candidate_count": sum(
                len(item.get("dimension_rejections", [])) for item in results
            ),
        },
        "instance_group_resolution": {
            "schema": "codex_trellis_instance_group_asset_resolution_v1",
            "group_count": len(brief.get("instance_groups", [])),
            "groups": [
                {
                    "group_id": str(group.get("group_id") or ""),
                    "member_results": [
                        {
                            "object_id": str(member.get("object_id") or ""),
                            "role": str(member.get("role") or ""),
                            "asset_id": next(
                                (
                                    item.get("asset_id")
                                    for item in results
                                    if str(item.get("object_id") or "")
                                    == str(member.get("object_id") or "")
                                ),
                                None,
                            ),
                            "asset_family": next(
                                (
                                    item.get("instance_group_asset_family")
                                    for item in results
                                    if str(item.get("object_id") or "")
                                    == str(member.get("object_id") or "")
                                ),
                                None,
                            ),
                            "strategy": next(
                                (
                                    item.get("instance_group_asset_strategy")
                                    for item in results
                                    if str(item.get("object_id") or "")
                                    == str(member.get("object_id") or "")
                                ),
                                None,
                            ),
                            "pair_role": next(
                                (
                                    item.get("asset_pair_role")
                                    for item in results
                                    if str(item.get("object_id") or "")
                                    == str(member.get("object_id") or "")
                                ),
                                None,
                            ),
                            "source_pair_role": next(
                                (
                                    item.get("asset_source_pair_role")
                                    for item in results
                                    if str(item.get("object_id") or "")
                                    == str(member.get("object_id") or "")
                                ),
                                None,
                            ),
                            "medial_axis": next(
                                (
                                    item.get("asset_medial_axis")
                                    for item in results
                                    if str(item.get("object_id") or "")
                                    == str(member.get("object_id") or "")
                                ),
                                None,
                            ),
                            "handedness_provenance": next(
                                (
                                    item.get("asset_handedness_provenance")
                                    for item in results
                                    if str(item.get("object_id") or "")
                                    == str(member.get("object_id") or "")
                                ),
                                None,
                            ),
                            "reflection_axis": next(
                                (
                                    item.get("asset_reflection_axis")
                                    for item in results
                                    if str(item.get("object_id") or "")
                                    == str(member.get("object_id") or "")
                                ),
                                None,
                            ),
                        }
                        for member in group.get("members", [])
                        if isinstance(member, dict)
                    ],
                }
                for group in brief.get("instance_groups", [])
                if isinstance(group, dict)
            ],
        },
    }
    write_json(output_dir / "asset_resolution.json", report)
    if multiview_semantic_scorer is not None:
        multiview_semantic_scorer.close()
    return report
