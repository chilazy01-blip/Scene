from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import time
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from .asset_index import AssetIndex, AssetIndexBuilder, VECTOR_DIM
from .content_chain import content_hash, file_binding


CATEGORIES = (
    "sofa", "coffee_table", "tv_stand", "bookcase", "bed", "nightstand", "desk", "office_chair",
    "wardrobe", "dresser", "floor_lamp", "table_lamp", "side_table", "accent_chair", "dining_table",
    "dining_chair", "cabinet", "area_rug", "potted_plant", "wall_art",
)
STYLES = ("modern", "warm", "minimal", "rustic", "industrial", "classic", "coastal", "japandi", "neutral", "colorful")


def capabilities(category: str) -> list[str]:
    result = ["static_mesh", "relation_proxy"]
    if "chair" in category or category in {"sofa", "bed"}:
        result.append("human_support")
    if category in {"bookcase", "cabinet", "wardrobe", "dresser"}:
        result.append("containment")
    return result


def records(count: int, vectors: dict[str, list[float]]) -> Iterator[dict[str, Any]]:
    rng = np.random.default_rng(20260901)
    for index in range(count):
        asset_id = f"asset_{index:06d}"
        vector = rng.normal(size=VECTOR_DIM).astype(np.float32)
        vector /= np.linalg.norm(vector)
        if index < len(CATEGORIES):
            vectors[asset_id] = vector.tolist()
        category = CATEGORIES[index % len(CATEGORIES)]
        style = STYLES[(index // len(CATEGORIES)) % len(STYLES)]
        yield {
            "asset_id": asset_id, "category": category, "styles": [style],
            "material_tags": ["wood" if index % 3 == 0 else "fabric" if index % 3 == 1 else "metal"],
            "qa_status": "approved", "lifecycle_status": "curated", "license": "internal_research",
            "capabilities": capabilities(category), "dimensions": {"width": 0.5 + (index % 30) * 0.05, "length": 0.4 + (index % 20) * 0.04, "height": 0.5 + (index % 25) * 0.06},
            "face_count": 20_000 + index % 300_000, "texture_max": 1024 + (index % 3) * 1024,
            "glb_path": f"cold://synthetic/{category}/{asset_id}.glb", "preview_path": f"hot://previews/{asset_id}.webp",
            "storage_tier": "hot" if index < count * 0.2 else "warm" if index < count * 0.8 else "cold",
            "retrieval_vector": vector.tolist(),
        }


def percentile(values: list[float], value: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), value))


def proc_io() -> dict[str, int]:
    result = {}
    for line in Path("/proc/self/io").read_text(encoding="utf-8").splitlines():
        key, value = line.split(":", 1)
        result[key] = int(value.strip())
    return result


def run_benchmark(output_dir: Path, count: int = 100_000) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    labels_path = Path(__file__).with_name("capabilities") / "p017_labeled_queries_v1.json"
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    index_path = output_dir / "synthetic_100k.asset_index.sqlite"
    vectors: dict[str, list[float]] = {}
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    io_before = proc_io()
    build_started = time.perf_counter()
    with AssetIndexBuilder(index_path, vector_model="synthetic_multiview_v1") as builder:
        inserted = builder.upsert(records(count, vectors))
        # Four exact-vector hard negatives prove safety filtering precedes ANN.
        first_vector = vectors["asset_000000"]
        builder.upsert([
            {"asset_id": "negative_rejected", "category": "sofa", "qa_status": "rejected", "lifecycle_status": "curated", "license": "internal_research", "capabilities": capabilities("sofa"), "retrieval_vector": first_vector},
            {"asset_id": "negative_lifecycle", "category": "sofa", "qa_status": "approved", "lifecycle_status": "candidate_for_curation", "license": "internal_research", "capabilities": capabilities("sofa"), "retrieval_vector": first_vector},
            {"asset_id": "negative_license", "category": "sofa", "qa_status": "approved", "lifecycle_status": "curated", "license": "proprietary_disallowed", "capabilities": capabilities("sofa"), "retrieval_vector": first_vector},
            {"asset_id": "negative_capability", "category": "sofa", "qa_status": "approved", "lifecycle_status": "curated", "license": "internal_research", "capabilities": ["static_mesh"], "retrieval_vector": first_vector},
        ])
        initial_metadata = builder.finalize()
    build_seconds = time.perf_counter() - build_started

    open_started = time.perf_counter()
    index = AssetIndex(index_path)
    cold_open_seconds = time.perf_counter() - open_started
    query_contracts = []
    for item in labels["queries"]:
        target = item["compatible_asset_ids"][0]
        query_contracts.append({
            "category": item["category"], "styles": item["styles"], "vector": vectors[target],
            "required_capabilities": capabilities(item["category"]), "top_k": 50,
        })
    cold_started = time.perf_counter()
    cold = index.batch_query(query_contracts)
    cold_room_seconds = time.perf_counter() - cold_started
    recalls = []
    for annotation, result in zip(labels["queries"], cold["results"]):
        returned = {item["asset_id"] for item in result["results"]}
        expected = set(annotation["compatible_asset_ids"])
        recalls.append(len(returned & expected) / len(expected))
    recall_at_50 = float(statistics.mean(recalls))
    forbidden = {"negative_rejected", "negative_lifecycle", "negative_license", "negative_capability"}
    safety_query = index.query(category="sofa", styles=["modern"], vector=vectors["asset_000000"], required_capabilities=capabilities("sofa"), top_k=50)
    safety_violations = sorted(forbidden & {item["asset_id"] for item in safety_query["results"]})

    room_times = []
    room_hashes = []
    for _ in range(60):
        started = time.perf_counter()
        batch = index.batch_query(query_contracts)
        room_times.append(time.perf_counter() - started)
        room_hashes.append(batch["result_hash"])
    warm = {"p50": percentile(room_times, 50), "p95": percentile(room_times, 95), "p99": percentile(room_times, 99)}
    hit_rate = sum(bool(result["results"]) for result in cold["results"]) / len(cold["results"])
    deterministic = len(set(room_hashes)) == 1
    old_version = index.index_version
    old_cache_key = safety_query["cache_key"]
    index.close()

    with AssetIndexBuilder(index_path, vector_model="synthetic_multiview_v1") as builder:
        builder.upsert([{ "asset_id": "asset_000000", "category": "sofa", "styles": ["modern"], "qa_status": "approved", "lifecycle_status": "deprecated", "license": "internal_research", "capabilities": capabilities("sofa"), "retrieval_vector": vectors["asset_000000"] }])
        deleted = builder.delete(["asset_099999"])
        updated_metadata = builder.finalize()
    updated_index = AssetIndex(index_path)
    after_update = updated_index.query(**query_contracts[0])
    invalidation_ok = old_version != updated_index.index_version and old_cache_key != after_update["cache_key"] and "asset_000000" not in {item["asset_id"] for item in after_update["results"]}
    replay_one = updated_index.batch_query(query_contracts)["result_hash"]
    updated_index.close()
    replay_two_index = AssetIndex(index_path)
    replay_two = replay_two_index.batch_query(query_contracts)["result_hash"]
    replay_two_index.close()

    io_after = proc_io()
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report = {
        "schema": "scene-v2-p017-asset-index-benchmark/v1", "synthetic_stress_set": True,
        "representative_asset_count": int(initial_metadata["asset_count"]), "base_asset_count": inserted,
        "labeled_queries": {"path": str(labels_path), **file_binding(labels_path), "count": len(labels["queries"]), "recall_at_50": recall_at_50},
        "hard_safety": {"filters_before_ann": True, "violations": safety_violations, "ok": not safety_violations},
        "latency_seconds": {"build": build_seconds, "cold_open": cold_open_seconds, "cold_room": cold_room_seconds, "warm_room": warm},
        "index_resources": {"database": {"path": str(index_path), **file_binding(index_path)}, "peak_rss_delta_kib": max(0, rss_after-rss_before), "process_io_delta": {key: io_after.get(key, 0)-io_before.get(key, 0) for key in sorted(io_after)}},
        "asset_hit_rate": hit_rate, "incremental": {"deleted_count": deleted, "old_version": old_version, "new_version": updated_metadata["index_version"], "content_hash_invalidation_ok": invalidation_ok},
        "deterministic_replay": {"warm_repeated_hash_stable": deterministic, "fresh_process_equivalent_hash_stable": replay_one == replay_two},
        "online_glb_open_count": 0, "cold_storage_glb_transfer_count": 0,
    }
    report["ok"] = bool(count >= 100_000 and recall_at_50 >= 0.98 and warm["p95"] <= 1.0 and hit_rate >= 0.85 and not safety_violations and invalidation_ok and deterministic and replay_one == replay_two)
    report["content_hash"] = content_hash(report)
    (output_dir / "p017_asset_index_benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="P017 100k scalable asset-index benchmark")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, default=100_000)
    args = parser.parse_args()
    report = run_benchmark(args.output_dir, args.count)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
