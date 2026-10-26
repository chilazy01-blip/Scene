"""Offline asset ingestion and deterministic layered online retrieval."""

from __future__ import annotations

import itertools
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .content_chain import content_hash, file_binding


INDEX_SCHEMA = "scene-v2-asset-index/v1"
VECTOR_DIM = 16
LSH_BITS = 12
ANN_RECALL_LIMIT = 500
RERANK_LIMIT = 50


def normalized_vector(value: Sequence[float]) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32)
    if vector.shape != (VECTOR_DIM,):
        raise ValueError(f"asset vector must have {VECTOR_DIM} dimensions")
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 1e-9:
        raise ValueError("asset vector must have a finite non-zero norm")
    return vector / norm


def text_vector(tokens: Iterable[str]) -> np.ndarray:
    """Deterministic local feature hashing; model vectors may replace it offline."""

    vector = np.zeros(VECTOR_DIM, dtype=np.float32)
    for raw in sorted({str(item).strip().lower() for item in tokens if str(item).strip()}):
        digest = bytes.fromhex(content_hash(raw))
        for offset in range(0, 16, 2):
            index = digest[offset] % VECTOR_DIM
            vector[index] += 1.0 if digest[offset + 1] & 1 else -1.0
    if not np.any(vector):
        vector[0] = 1.0
    return normalized_vector(vector)


def _hyperplanes() -> np.ndarray:
    rng = np.random.default_rng(170017)
    return np.asarray(rng.normal(size=(LSH_BITS, VECTOR_DIM)), dtype=np.float32)


HYPERPLANES = _hyperplanes()


def lsh_code(vector: np.ndarray) -> int:
    bits = np.dot(HYPERPLANES, vector) >= 0.0
    return sum((1 << index) for index, enabled in enumerate(bits) if bool(enabled))


def multiprobe_codes(code: int, radius: int = 4) -> list[int]:
    result = [code]
    for distance in range(1, radius + 1):
        for bits in itertools.combinations(range(LSH_BITS), distance):
            neighbor = code
            for bit in bits:
                neighbor ^= 1 << bit
            result.append(neighbor)
    return result


def normalize_asset_record(record: dict[str, Any]) -> tuple[dict[str, Any], np.ndarray]:
    item = json.loads(json.dumps(record))
    asset_id = str(item.get("asset_id") or "").strip()
    category = str(item.get("category") or "").strip()
    if not asset_id or not category:
        raise ValueError("indexed assets require asset_id and category")
    item["asset_id"] = asset_id
    item["category"] = category
    item["qa_status"] = str(item.get("qa_status") or "approved")
    item["lifecycle_status"] = str(item.get("lifecycle_status") or "curated")
    item["license"] = str(item.get("license") or "internal_research")
    item["styles"] = sorted({str(value).lower() for value in item.get("styles", [])})
    item["capabilities"] = sorted({str(value) for value in item.get("capabilities", [])})
    vector_value = item.pop("retrieval_vector", None)
    vector = normalized_vector(vector_value) if vector_value is not None else text_vector(
        [category, *item["styles"], *item.get("material_tags", [])]
    )
    item["index_record_hash"] = content_hash(item)
    return item, vector


class AssetIndexBuilder:
    def __init__(self, path: Path, *, source_manifest: Path | None = None, vector_model: str = "feature_hash_v1") -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.source_manifest = source_manifest
        self.vector_model = vector_model
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS assets(
              asset_id TEXT PRIMARY KEY, category TEXT NOT NULL, qa_status TEXT NOT NULL,
              lifecycle TEXT NOT NULL, license TEXT NOT NULL, family_id TEXT, pair_role TEXT,
              width REAL, length REAL, height REAL, face_count INTEGER, texture_max INTEGER,
              lsh INTEGER NOT NULL, vector BLOB NOT NULL, record_hash TEXT NOT NULL,
              metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS capabilities(asset_id TEXT NOT NULL, capability TEXT NOT NULL,
              PRIMARY KEY(asset_id,capability), FOREIGN KEY(asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS index_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_assets_hard ON assets(category,qa_status,lifecycle,license,lsh);
            CREATE INDEX IF NOT EXISTS idx_assets_family ON assets(family_id,pair_role);
            CREATE INDEX IF NOT EXISTS idx_capability ON capabilities(capability,asset_id);
            """
        )
        self.db.execute("PRAGMA foreign_keys=ON")

    def upsert(self, records: Iterable[dict[str, Any]], *, commit_every: int = 5000) -> int:
        count = 0
        for raw in records:
            item, vector = normalize_asset_record(raw)
            dimensions = item.get("dimensions") if isinstance(item.get("dimensions"), dict) else {}
            self.db.execute(
                """INSERT INTO assets(asset_id,category,qa_status,lifecycle,license,family_id,pair_role,
                   width,length,height,face_count,texture_max,lsh,vector,record_hash,metadata_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET
                   category=excluded.category,qa_status=excluded.qa_status,lifecycle=excluded.lifecycle,
                   license=excluded.license,family_id=excluded.family_id,pair_role=excluded.pair_role,
                   width=excluded.width,length=excluded.length,height=excluded.height,face_count=excluded.face_count,
                   texture_max=excluded.texture_max,lsh=excluded.lsh,vector=excluded.vector,
                   record_hash=excluded.record_hash,metadata_json=excluded.metadata_json""",
                (
                    item["asset_id"], item["category"], item["qa_status"], item["lifecycle_status"], item["license"],
                    item.get("asset_family_id"), item.get("pair_role"), dimensions.get("width"), dimensions.get("length"),
                    dimensions.get("height"), item.get("face_count"), item.get("texture_max"), lsh_code(vector),
                    vector.tobytes(), item["index_record_hash"], json.dumps(item, sort_keys=True, separators=(",", ":")),
                ),
            )
            self.db.execute("DELETE FROM capabilities WHERE asset_id=?", (item["asset_id"],))
            self.db.executemany(
                "INSERT INTO capabilities(asset_id,capability) VALUES(?,?)",
                ((item["asset_id"], capability) for capability in item["capabilities"]),
            )
            count += 1
            if count % commit_every == 0:
                self.db.commit()
        self.db.commit()
        return count

    def delete(self, asset_ids: Iterable[str]) -> int:
        count = 0
        for asset_id in asset_ids:
            count += self.db.execute("DELETE FROM assets WHERE asset_id=?", (str(asset_id),)).rowcount
        self.db.commit()
        return count

    def finalize(self) -> dict[str, Any]:
        rows = list(self.db.execute("SELECT asset_id,record_hash FROM assets ORDER BY asset_id"))
        index_version = content_hash({"schema": INDEX_SCHEMA, "vector_model": self.vector_model, "records": rows})
        values = {
            "schema": INDEX_SCHEMA,
            "index_version": index_version,
            "vector_model": self.vector_model,
            "vector_dim": str(VECTOR_DIM),
            "lsh_bits": str(LSH_BITS),
            "asset_count": str(len(rows)),
            "source_manifest_binding": json.dumps(file_binding(self.source_manifest), sort_keys=True) if self.source_manifest and self.source_manifest.is_file() else "null",
            "finalized_at": str(time.time()),
        }
        self.db.executemany("INSERT OR REPLACE INTO index_metadata(key,value) VALUES(?,?)", values.items())
        self.db.commit()
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {**values, "asset_count": len(rows), "source_manifest_binding": json.loads(values["source_manifest_binding"])}

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "AssetIndexBuilder":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class AssetIndex:
    def __init__(self, path: Path, *, expected_manifest: Path | None = None) -> None:
        uri = f"file:{path.resolve()}?mode=ro"
        self.path = path.resolve()
        self.db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.metadata = {row[0]: row[1] for row in self.db.execute("SELECT key,value FROM index_metadata")}
        if self.metadata.get("schema") != INDEX_SCHEMA:
            raise ValueError("asset index schema mismatch")
        if expected_manifest is not None:
            expected = file_binding(expected_manifest)
            recorded = json.loads(self.metadata.get("source_manifest_binding", "null"))
            if recorded != expected:
                raise ValueError("asset index is stale for current manifest bytes")
        self.index_version = self.metadata["index_version"]
        self.cache: dict[str, dict[str, Any]] = {}

    def query(
        self,
        *,
        category: str,
        styles: Sequence[str] = (),
        vector: Sequence[float] | None = None,
        family_id: str | None = None,
        asset_id: str | None = None,
        pair_role: str | None = None,
        license_allowlist: Sequence[str] = ("internal_research", "cc0", "cc-by"),
        required_capabilities: Sequence[str] = (),
        max_faces: int | None = None,
        max_texture: int | None = None,
        top_k: int = RERANK_LIMIT,
    ) -> dict[str, Any]:
        query_vector = normalized_vector(vector) if vector is not None else text_vector([category, *styles])
        contract = {
            "category": category, "styles": sorted(styles), "vector": query_vector.tolist(), "family_id": family_id,
            "asset_id": asset_id, "pair_role": pair_role, "license_allowlist": sorted(license_allowlist),
            "required_capabilities": sorted(required_capabilities), "max_faces": max_faces,
            "max_texture": max_texture, "top_k": int(top_k),
        }
        query_hash = content_hash(contract)
        cache_key = content_hash({"query_contract_hash": query_hash, "index_version": self.index_version})
        if cache_key in self.cache:
            cached = json.loads(json.dumps(self.cache[cache_key]))
            cached["cache_hit"] = True
            return cached
        codes = multiprobe_codes(lsh_code(query_vector))
        placeholders = ",".join("?" for _ in codes)
        clauses = ["category=?", "qa_status='approved'", "lifecycle='curated'", f"lsh IN ({placeholders})"]
        parameters: list[Any] = [category, *codes]
        if family_id:
            clauses.append("family_id=?"); parameters.append(family_id)
        if asset_id:
            clauses.append("asset_id=?"); parameters.append(asset_id)
        if pair_role:
            clauses.append("pair_role=?"); parameters.append(pair_role)
        if license_allowlist:
            clauses.append("license IN (" + ",".join("?" for _ in license_allowlist) + ")"); parameters.extend(license_allowlist)
        if max_faces is not None:
            clauses.append("(face_count IS NULL OR face_count<=?)"); parameters.append(int(max_faces))
        if max_texture is not None:
            clauses.append("(texture_max IS NULL OR texture_max<=?)"); parameters.append(int(max_texture))
        for capability in required_capabilities:
            clauses.append("EXISTS(SELECT 1 FROM capabilities c WHERE c.asset_id=assets.asset_id AND c.capability=?)")
            parameters.append(capability)
        rows = list(self.db.execute(
            f"SELECT asset_id,vector,metadata_json FROM assets WHERE {' AND '.join(clauses)} ORDER BY asset_id",
            parameters,
        ))
        if rows:
            matrix = np.frombuffer(b"".join(bytes(row["vector"]) for row in rows), dtype=np.float32).reshape((-1, VECTOR_DIM))
            scores = matrix @ query_vector
            take = min(len(rows), ANN_RECALL_LIMIT)
            indices = np.argpartition(-scores, take - 1)[:take] if take < len(rows) else np.arange(len(rows))
            ranked = sorted(((float(scores[index]), str(rows[index]["asset_id"]), int(index)) for index in indices), key=lambda value: (-value[0], value[1]))
        else:
            ranked = []
        results = []
        for score, _, index in ranked[: int(top_k)]:
            item = json.loads(rows[index]["metadata_json"])
            item["_index_vector_score"] = score
            results.append(item)
        result = {
            "schema": "scene-v2-asset-query-result/v1", "index_version": self.index_version,
            "query_contract_hash": query_hash, "cache_key": cache_key, "cache_hit": False,
            "hard_filtered_count": len(rows), "ann_recall_limit": ANN_RECALL_LIMIT,
            "rerank_limit": int(top_k), "results": results,
            "hard_filters_applied_before_vector_recall": True,
        }
        self.cache[cache_key] = json.loads(json.dumps(result))
        return result

    def batch_query(self, queries: Sequence[dict[str, Any]]) -> dict[str, Any]:
        started = time.perf_counter()
        results = [self.query(**query) for query in queries]
        return {
            "schema": "scene-v2-asset-batch-query/v1", "index_version": self.index_version,
            "query_count": len(queries), "duration_seconds": time.perf_counter() - started,
            "results": results, "result_hash": content_hash(results),
        }

    def close(self) -> None:
        self.db.close()
