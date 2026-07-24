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
from .instance_groups import member_group_index
from .orientation import solve_facing_yaw


ORIENTATION_METADATA_KEYS = (
    "asset_axis_to_z",
    "asset_axis_to_z_sign",
    "asset_local_yaw_offset_degrees",
    "footprint_yaw_offset_degrees",
    "asset_canonical_front",
    "asset_orientation",
    "asset_affordance",
    "usage_constraints",
)


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
    with _opener().open(req, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


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
        if self.manifest_path:
            payload = read_json(self.manifest_path)
            raw_assets = payload.get("assets", []) if isinstance(payload, dict) else []
            if not isinstance(raw_assets, list):
                raise ValueError(f"asset manifest 'assets' must be a list: {self.manifest_path}")
            self.assets = [item for item in raw_assets if isinstance(item, dict)]

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
    ) -> dict[str, Any] | None:
        candidates: list[tuple[tuple[int, float, int], str, dict[str, Any]]] = []
        wanted_styles = {style.lower() for style in styles}
        for item in self.assets:
            if str(item.get("category")) != category:
                continue
            if family_id and str(item.get("asset_family_id") or "") != family_id:
                continue
            if asset_id and str(item.get("asset_id") or "") != asset_id:
                continue
            if str(item.get("qa_status", "approved")) != "approved":
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
            candidates.append(
                (
                    (dimension_rank, dimension_error, -style_score),
                    str(item.get("asset_id", path.stem)),
                    resolved,
                )
            )
        if not candidates:
            return None
        candidates.sort(key=lambda row: (row[0], row[1]))
        best_score = candidates[0][0]
        best_candidates = [row for row in candidates if row[0] == best_score]
        return best_candidates[int(variant_index) % len(best_candidates)][2]


def _copy_asset(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == destination.resolve():
        return
    shutil.copy2(source, destination)


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


def _resolve_architecture_assets(
    brief: dict[str, Any],
    registry: AssetRegistry,
    asset_dir: Path,
    *,
    mode: str,
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
    if reference_image_path is not None:
        request_payload["reference_image_path"] = str(reference_image_path.resolve())
    deadline = time.time() + timeout
    status, accepted = _post_json(
        trellis_url.rstrip("/") + "/generate",
        request_payload,
        timeout=min(30.0, timeout),
    )
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
) -> dict[str, Any]:
    registry = AssetRegistry(manifest_path)
    asset_dir = output_dir / "assets_staged"
    results: list[dict[str, Any]] = []
    architecture_results = _resolve_architecture_assets(
        brief,
        registry,
        asset_dir,
        mode=mode,
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
            asset_contract = (
                group.get("asset_contract")
                if isinstance(group.get("asset_contract"), dict)
                else {}
            )
            family_id = str(group_primary.get("asset_family_id") or "")
            if family_id and str(asset_contract.get("match_mode") or "") == "same_family":
                matched = registry.find(
                    category,
                    list(brief.get("styles", [])),
                    variant_index=category_use_count.get(category, 0),
                    target_dimensions=requested_dimensions,
                    dimension_policy=dimension_policy,
                    rejections=dimension_rejections,
                    family_id=family_id,
                )
            if (
                matched is None
                and str(asset_contract.get("fallback") or "same_asset_reuse")
                == "same_asset_reuse"
            ):
                matched = registry.find(
                    category,
                    list(brief.get("styles", [])),
                    target_dimensions=requested_dimensions,
                    dimension_policy=dimension_policy,
                    rejections=dimension_rejections,
                    asset_id=str(group_primary.get("asset_id") or ""),
                )
        if matched is None:
            matched = registry.find(
                category,
                list(brief.get("styles", [])),
                variant_index=category_use_count.get(category, 0),
                target_dimensions=requested_dimensions,
                dimension_policy=dimension_policy,
                rejections=dimension_rejections,
            )
        if matched:
            if group_id and group_id not in selected_group_assets:
                selected_group_assets[group_id] = deepcopy(matched)
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
            if group_id:
                family_key = str(
                    matched.get("asset_family_id")
                    or f"same_asset:{matched.get('asset_id') or source.stem}"
                )
                obj["instance_group_asset_family"] = family_key
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
        prompt = render_asset_prompt(spec)
        fingerprint_payload = {
            "category": obj["category"],
            "prompt": prompt,
            "target_dimensions_m": spec["target_dimensions_m"],
        }
        generation_key = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        reuse_from = generation_units.get(generation_key)
        if reuse_from is None:
            generation_units[generation_key] = str(obj["id"])
        obj["asset_generation_spec"] = spec
        obj["asset_prompt"] = prompt
        obj["asset_generation_key"] = generation_key
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
                "strategy": obj["asset_generation_strategy"],
                "reuse_from_object_id": reuse_from,
                "asset_generation_spec": deepcopy(spec),
                "bridge_input_prompt": prompt,
                "final_flux_prompt": None,
                "prompt_metrics": {
                    "characters": len(prompt),
                    "words": len(prompt.split()),
                },
            }
        )

    unique_generation_count = len(generation_units)
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
            "generation_entries": generation_plan_entries,
        },
    )

    if mode == "trellis2" and unique_generation_count > max_new_assets:
        raise RuntimeError(
            f"Refusing to generate {unique_generation_count} unique new assets for "
            f"{len(missing)} missing instances; --max-new-assets={max_new_assets}"
        )
    health = None
    if mode == "trellis2" and missing:
        health = bridge_health(trellis_url)
        if not health.get("ok"):
            raise RuntimeError(f"TRELLIS.2 bridge is not healthy at {trellis_url}: {health}")

    generated_units: dict[str, dict[str, Any]] = {}
    generation_call_index = 0
    for obj in missing:
        destination = asset_dir / f"{obj['id']}.glb"
        requested_dimensions = deepcopy(obj["requested_dimensions"])
        if mode == "trellis2":
            generation_key = str(obj["asset_generation_key"])
            generated = generated_units.get(generation_key)
            if generated is None:
                metadata = generate_trellis_asset(
                    obj,
                    destination,
                    trellis_url=trellis_url,
                    seed=seed + generation_call_index,
                    timeout=timeout,
                    steps=steps,
                    texture_size=texture_size,
                    decimation_target=decimation_target,
                    pipeline_type=pipeline_type,
                    preprocess_image=preprocess_image,
                )
                generation_call_index += 1
                obj["asset_id"] = f"generated_{obj['id']}_{metadata['job_id']}"
                obj["asset_source"] = "trellis2_staging"
                generated_units[generation_key] = {
                    "path": destination,
                    "asset_id": obj["asset_id"],
                    "object_id": str(obj["id"]),
                    "metadata": metadata,
                    "final_flux_prompt": _final_flux_prompt(metadata),
                }
            else:
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
            obj["final_flux_prompt"] = (
                _final_flux_prompt(metadata)
                if generated is None
                else str(generated.get("final_flux_prompt") or "") or None
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
            write_json(asset_dir / f"{obj['id']}.json", {"object": obj, **metadata})
            status = "generated"
        else:
            obj["asset_id"] = f"planned_{obj['category']}"
            obj["asset_source"] = "missing_generation_plan"
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
                "generation_strategy": obj.get("asset_generation_strategy"),
                "generation_reuse_from": obj.get("asset_generation_reuse_from"),
                "asset_generation_spec": deepcopy(obj.get("asset_generation_spec")),
                "bridge_input_prompt": obj.get("asset_prompt"),
                "final_flux_prompt": obj.get("final_flux_prompt"),
                "instance_group_id": obj.get("instance_group_id"),
                "instance_group_role": obj.get("instance_group_role"),
                "instance_group_asset_family": obj.get(
                    "instance_group_asset_family"
                ),
                "instance_group_asset_strategy": obj.get(
                    "instance_group_asset_strategy"
                ),
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
    report = {
        "schema": "codex_trellis_asset_resolution_v2",
        "mode": mode,
        "manifest": str(manifest_path.resolve()) if manifest_path else None,
        "asset_dir": str(asset_dir),
        "missing_asset_generation_plan": str(generation_plan_path),
        "bridge_health": health,
        "results": results,
        "architecture_results": architecture_results,
        "component_resolution": deepcopy(component_resolution),
        "component_resolution_ok": component_resolution_ok,
        "missing_count": sum(1 for item in results if item["status"] == "planned_missing"),
        "generated_count": sum(1 for item in results if item["status"] == "generated"),
        "unique_generated_count": generation_call_index,
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
        "ready_for_assembly": component_resolution_ok
        and all(item["status"] in {"generated", "reused"} for item in results),
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
    return report
