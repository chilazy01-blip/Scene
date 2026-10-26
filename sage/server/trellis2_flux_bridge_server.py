#!/usr/bin/env python3
"""SAGE-compatible TRELLIS server backed by Flux text-to-image plus TRELLIS.2 image-to-3D."""

from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from contextlib import contextmanager
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from PIL import Image
import numpy as np

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from sage.experiments.codex_trellis_scene_v2.scene_dna_semantic import (
    DinoV3PrototypeScorer,
    Siglip2SemanticScorer,
    combine_semantic_form_style_scores,
    score_form_contract,
    selection_uncertainty,
    form_improvement_guard,
)
from sage.experiments.codex_trellis_scene_v2.alpha_hygiene import (
    audit_sanitized_alpha_edges,
    clean_chromatic_alpha_edges,
    composite_on_review_background,
)
from sage.experiments.codex_trellis_scene_v2.scene_dna_vnext import (
    assess_2d_generability,
    select_vnext_candidate,
)
from sage.experiments.codex_trellis_scene_v2.heavy_job_broker import HeavyJobBroker
from sage.experiments.codex_trellis_scene_v2.core_domain import IMAGE_PROVIDERS
from sage.experiments.codex_trellis_scene_v2.native_alpha_normalization import (
    EVIDENCE_SCHEMA as NATIVE_ALPHA_EVIDENCE_SCHEMA,
    POLICY as NATIVE_ALPHA_POLICY,
    decode_native_alpha,
    normalization_content_key,
    opacity_review_ok,
    prepare_native_alpha_evidence,
    write_immutable,
)


BRIDGE_IMAGE_PROVIDERS = (*IMAGE_PROVIDERS, "flux2-klein")


def provider_route(path: str) -> tuple[str, str | None]:
    """Expose a provider-scoped API without changing the asset resolver."""
    if not path.startswith("/providers/"):
        return path, None
    parts = path.split("/", 3)
    if len(parts) != 4 or parts[2] not in BRIDGE_IMAGE_PROVIDERS:
        raise ValueError("Unknown image provider route")
    return "/" + parts[3], parts[2]


class JobStore:
    def __init__(self, root: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self.root = root
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)
            for path in sorted(root.glob("*.json")):
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("status") == "processing":
                    record["status"] = "interrupted"
                    record["interrupted_at"] = time.time()
                self._jobs[path.stem] = record
                self._persist(path.stem)

    def _persist(self, job_id: str) -> None:
        if self.root is None:
            return
        if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
            raise ValueError("Invalid bridge job id")
        path = self.root / f"{job_id}.json"
        partial = path.with_suffix(".json.partial")
        with partial.open("w", encoding="utf-8") as stream:
            json.dump(self._jobs[job_id], stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        partial.replace(path)

    def create(self, job_id: str | None = None, **initial: Any) -> str:
        job_id = job_id or uuid.uuid4().hex
        with self._lock:
            previous = self._jobs.get(job_id, {})
            if previous and previous.get("status") not in {"interrupted", "waiting_for_image_provider"}:
                raise ValueError("Only interrupted bridge jobs can be resumed")
            self._jobs[job_id] = {**previous, **initial, "status": "processing", "created_at": previous.get("created_at", time.time())}
            self._persist(job_id)
        return job_id

    def update(self, job_id: str, **payload: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(payload)
            self._persist(job_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None


def _is_loopback_url(url: str) -> bool:
    host = urlparse(url).hostname
    return host in {"127.0.0.1", "localhost", "::1"}


def _trellis2_model_names_for_pipeline(pipeline_type: str) -> list[str]:
    base = [
        "sparse_structure_flow_model",
        "sparse_structure_decoder",
        "shape_slat_decoder",
        "tex_slat_decoder",
    ]
    if pipeline_type == "512":
        return base + ["shape_slat_flow_model_512", "tex_slat_flow_model_512"]
    if pipeline_type == "1024":
        return base + ["shape_slat_flow_model_1024", "tex_slat_flow_model_1024"]
    if pipeline_type == "1024_cascade":
        return base + [
            "shape_slat_flow_model_512",
            "shape_slat_flow_model_1024",
            "tex_slat_flow_model_512",
            "tex_slat_flow_model_1024",
        ]
    if pipeline_type == "1536_cascade":
        return base + [
            "shape_slat_flow_model_512",
            "shape_slat_flow_model_1024",
            "tex_slat_flow_model_512",
            "tex_slat_flow_model_1024",
        ]
    return base + [
        "shape_slat_flow_model_512",
        "shape_slat_flow_model_1024",
        "tex_slat_flow_model_512",
        "tex_slat_flow_model_1024",
    ]


@contextmanager
def _open_url_no_proxy_for_loopback(req_or_url: Any, timeout: float):
    url = req_or_url.full_url if hasattr(req_or_url, "full_url") else str(req_or_url)
    if _is_loopback_url(url):
        opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
        with opener.open(req_or_url, timeout=timeout) as resp:
            yield resp
        return
    with urlrequest.urlopen(req_or_url, timeout=timeout) as resp:
        yield resp


def post_json(url: str, payload: dict[str, Any], timeout: float = 30.0) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with _open_url_no_proxy_for_loopback(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def get_bytes(url: str, timeout: float = 30.0) -> tuple[int, bytes, str]:
    try:
        with _open_url_no_proxy_for_loopback(url, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


class Trellis2BridgeRuntime:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self._lock = threading.Lock()
        self._pipeline = None
        self._torch = None
        self._o_voxel = None
        self._rembg_model = None
        self._rembg_transform = None
        self._rembg_to_pil = None
        self._rembg_torch = None
        self._rembg_lock = threading.Lock()
        self._semantic_scorer = None
        self._anchor_scorer = None
        self._semantic_scorer_lock = threading.Lock()

    @staticmethod
    def _path_is_temporary_storage(path: Path) -> bool:
        """Return whether ``path`` is under an OS volatile temporary root."""

        resolved = path.expanduser().resolve()
        return any(
            resolved == root or resolved.is_relative_to(root)
            for root in (Path("/tmp"), Path("/var/tmp"))
        )

    def _persistent_evidence_root(self, job_id: str | None = None) -> Path:
        """Resolve fail-closed storage for raw/RGBA generation evidence.

        The bridge output may deliberately live on fast temporary storage, but
        source evidence must not disappear with that directory.  A temporary
        output therefore requires an explicit non-temporary evidence root.
        """

        output_root = Path(self.args.output_dir).expanduser().resolve()
        configured = str(
            getattr(self.args, "persistent_evidence_dir", "") or ""
        ).strip()
        evidence_root = (
            Path(configured).expanduser().resolve()
            if configured
            else output_root / "generation_evidence"
        )
        if self._path_is_temporary_storage(evidence_root):
            raise RuntimeError(
                "Flux/TRELLIS evidence storage must be persistent; "
                "set --persistent-evidence-dir outside /tmp and /var/tmp"
            )
        evidence_root.mkdir(parents=True, exist_ok=True)
        if job_id is None:
            return evidence_root
        job_root = evidence_root / str(job_id)
        job_root.mkdir(parents=True, exist_ok=True)
        return job_root

    @staticmethod
    def _evidence_file_record(path: Path) -> dict[str, Any]:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "sha256": digest.hexdigest(),
        }

    @staticmethod
    def _copy_evidence_file(source: Path, destination: Path, *, immutable: bool = False) -> Path:
        source = source.expanduser().resolve()
        destination = destination.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if immutable:
            write_immutable(destination, source.read_bytes())
            return destination
        if source != destination:
            temporary = destination.with_name(destination.name + ".partial")
            shutil.copy2(source, temporary)
            temporary.replace(destination)
        return destination

    def _persisted_generated_reference_provenance(
        self, path: Path
    ) -> dict[str, Any] | None:
        """Verify that a direct reference came from an earlier Flux attempt."""

        path = path.expanduser().resolve()
        if not path.is_file() or len(path.parents) < 2:
            return None
        job_root = path.parent.parent
        manifest_path = job_root / "attempts" / f"{path.stem}.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if manifest.get("schema") not in {
            "scene-v2-flux-trellis-reference-evidence/v1",
            "scene-v2-image-trellis-reference-evidence/v2",
            NATIVE_ALPHA_EVIDENCE_SCHEMA,
        }:
            return None
        if manifest.get("reference_origin") not in {
            "flux_generated",
            "persisted_flux_generated_reference",
            "builtin_imagegen_generated",
            "persisted_builtin_imagegen_reference",
            "reprocessed_builtin_imagegen_reference",
        }:
            return None
        actual = self._evidence_file_record(path)
        if manifest.get("schema") == NATIVE_ALPHA_EVIDENCE_SCHEMA:
            if actual != (manifest.get("files") or {}).get("source_raw"):
                return None
        matches = any(
            isinstance(record, dict)
            and str(record.get("path") or "") == actual["path"]
            and int(record.get("bytes", -1)) == actual["bytes"]
            and str(record.get("sha256") or "") == actual["sha256"]
            for record in (manifest.get("files") or {}).values()
        )
        if not matches:
            return None
        if manifest.get("schema") in {"scene-v2-image-trellis-reference-evidence/v2", NATIVE_ALPHA_EVIDENCE_SCHEMA}:
            from sage.experiments.codex_trellis_scene_v2.asset_source_policy import validate_reference_evidence
            if not validate_reference_evidence({**manifest, "manifest": self._evidence_file_record(manifest_path)})["ok"]:
                return None
        return {
            "manifest": self._evidence_file_record(manifest_path),
            "reference": actual,
        }

    def _persist_reference_attempt_evidence(
        self,
        parent_job_id: str,
        attempt: dict[str, Any],
    ) -> dict[str, Any]:
        """Copy one Flux/RMBG attempt into immutable, hash-bound storage."""

        job_root = self._persistent_evidence_root(parent_job_id)
        reference_job_id = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            str(attempt.get("reference_job_id") or parent_job_id),
        )
        files: dict[str, dict[str, Any]] = {}
        native_normalization = (attempt.get("alpha_metadata") or {}).get("native_alpha_normalization")
        native = isinstance(native_normalization, dict)
        source_value = attempt.get("source_image_path")
        replay_reference = attempt.get("replay_reference_evidence")
        upstream_reference = replay_reference or (
            self._persisted_generated_reference_provenance(
                Path(str(source_value))
            )
            if source_value and not bool(attempt.get("generated"))
            else None
        )

        if source_value:
            source = Path(str(source_value))
            suffix = source.suffix.lower() if source.suffix else ".png"
            persisted = self._copy_evidence_file(
                source,
                job_root / "reference_images" / f"{reference_job_id}{suffix}",
                immutable=native,
            )
            attempt["source_image_path"] = str(persisted)
            files["source_rgb"] = self._evidence_file_record(persisted)

        prepared_value = attempt.get("prepared_image_path")
        if prepared_value:
            prepared = Path(str(prepared_value))
            persisted = self._copy_evidence_file(
                prepared,
                job_root / "reference_rgba" / f"{reference_job_id}.png",
                immutable=native,
            )
            attempt["prepared_image_path"] = str(persisted)
            files["prepared_rgba"] = self._evidence_file_record(persisted)

        alpha_metadata = attempt.get("alpha_metadata")
        if isinstance(alpha_metadata, dict):
            alpha_metadata = json.loads(json.dumps(alpha_metadata))
            if "source_rgb" in files:
                alpha_metadata["source_image_path"] = files["source_rgb"]["path"]
            if "prepared_rgba" in files:
                alpha_metadata["prepared_image_path"] = files["prepared_rgba"]["path"]
            mask_value = alpha_metadata.get("mask_path")
            if mask_value:
                mask = self._copy_evidence_file(
                    Path(str(mask_value)),
                    job_root / "reference_masks" / f"{reference_job_id}.png",
                    immutable=native,
                )
                alpha_metadata["mask_path"] = str(mask)
                files["alpha_mask"] = self._evidence_file_record(mask)
            normalized_white_value = alpha_metadata.get(
                "normalized_white_image_path"
            )
            if normalized_white_value:
                normalized_white = self._copy_evidence_file(
                    Path(str(normalized_white_value)),
                    job_root / "reference_white_rgb" / f"{reference_job_id}.png",
                    immutable=native,
                )
                alpha_metadata["normalized_white_image_path"] = str(
                    normalized_white
                )
                isolation = alpha_metadata.get("white_background_isolation")
                if isinstance(isolation, dict):
                    isolation["normalized_white_rgb_path"] = str(normalized_white)
                files["normalized_white_rgb"] = self._evidence_file_record(
                    normalized_white
                )
            if native:
                files["source_raw"] = files["source_rgb"]
                normalization = alpha_metadata["native_alpha_normalization"]
                normalization["records"]["source_raw"] = files["source_raw"]
                for name in ("native_alpha_mask", "source_visible_white_rgb"):
                    persisted = self._copy_evidence_file(
                        Path(normalization["records"][name]["path"]),
                        job_root / name / f"{reference_job_id}.png",
                        immutable=True,
                    )
                    files[name] = self._evidence_file_record(persisted)
                    normalization["records"][name] = files[name]
                if normalization["content_key"] != normalization_content_key(normalization):
                    raise ValueError("Native alpha normalization changed during persistence")
                alpha_metadata["source_white_input_path"] = files["source_visible_white_rgb"]["path"]
                alpha_metadata["source_white_background"]["source_image_path"] = files["source_visible_white_rgb"]["path"]
                alpha_metadata["source_white_background"]["source_image_sha256"] = files["source_visible_white_rgb"]["sha256"]
                normalization_path = job_root / "input_normalization_metadata" / f"{reference_job_id}.json"
                write_immutable(normalization_path, json.dumps(normalization, indent=2).encode("utf-8"))
                files["input_normalization_metadata"] = self._evidence_file_record(normalization_path)
            alpha_path = job_root / "alpha_metadata" / f"{reference_job_id}.json"
            alpha_path.parent.mkdir(parents=True, exist_ok=True)
            partial = alpha_path.with_name(alpha_path.name + ".partial")
            if native:
                write_immutable(alpha_path, json.dumps(alpha_metadata, indent=2, ensure_ascii=False).encode("utf-8"))
            else:
                partial.write_text(json.dumps(alpha_metadata, indent=2, ensure_ascii=False), encoding="utf-8")
                partial.replace(alpha_path)
            files["alpha_metadata"] = self._evidence_file_record(alpha_path)
            attempt["alpha_metadata"] = alpha_metadata

        manifest = {
            "schema": "scene-v2-flux-trellis-reference-evidence/v1",
            "parent_job_id": str(parent_job_id),
            "reference_job_id": reference_job_id,
            "reference_origin": (
                "flux_generated"
                if bool(attempt.get("generated"))
                else (
                    "persisted_flux_generated_reference"
                    if upstream_reference is not None
                    else "direct_reference_requires_upstream_provenance"
                )
            ),
            "upstream_reference": upstream_reference,
            "files": files,
            "complete": all(
                name in files
                for name in (
                    "source_rgb",
                    "prepared_rgba",
                    "alpha_mask",
                    "alpha_metadata",
                    "normalized_white_rgb",
                )
            ),
        }
        provider_metadata = attempt.get("image_provider_metadata")
        if attempt.get("image_provider") == "flux2-klein":
            manifest["image_provider"] = "flux2-klein"
        if attempt.get("image_provider") == "builtin_imagegen":
            if not isinstance(provider_metadata, dict):
                raise ValueError("Builtin source has no provider metadata")
            provider_path = job_root / "provider_metadata" / f"{reference_job_id}.json"
            provider_path.parent.mkdir(parents=True, exist_ok=True)
            provider_partial = provider_path.with_suffix(".json.partial")
            if native:
                write_immutable(provider_path, json.dumps(provider_metadata, indent=2).encode("utf-8"))
            else:
                provider_partial.write_text(json.dumps(provider_metadata, indent=2), encoding="utf-8")
                provider_partial.replace(provider_path)
            files["image_provider_metadata"] = self._evidence_file_record(provider_path)
            manifest.update({
                "schema": NATIVE_ALPHA_EVIDENCE_SCHEMA if native else "scene-v2-image-trellis-reference-evidence/v2",
                "reference_origin": (
                    "reprocessed_builtin_imagegen_reference" if replay_reference
                    else "builtin_imagegen_generated" if attempt.get("generated")
                    else "persisted_builtin_imagegen_reference" if upstream_reference
                    else "direct_reference_requires_upstream_provenance"
                ),
                "image_provider": "builtin_imagegen",
                "image_provider_metadata": provider_metadata,
            })
            if replay_reference:
                if not native:
                    raise ValueError("Explicit raw replay requires native-alpha evidence")
                manifest["replay_reference_evidence"] = upstream_reference
                processing_contract = {
                    "schema": "scene-v2-native-alpha-reprocessing-contract/v1",
                    "native_alpha_normalization_content_key": alpha_metadata["native_alpha_normalization"]["content_key"],
                    "source_raw_sha256": files["source_raw"]["sha256"],
                    "original_request_sha256": provider_metadata["request_sha256"],
                }
                manifest["processing_contract"] = processing_contract
                attempt["processing_contract"] = processing_contract
        manifest_path = job_root / "attempts" / f"{reference_job_id}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        partial = manifest_path.with_name(manifest_path.name + ".partial")
        if native:
            write_immutable(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
        else:
            partial.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            partial.replace(manifest_path)
        attempt["persistent_evidence"] = {
            **manifest,
            "manifest": self._evidence_file_record(manifest_path),
        }
        return attempt

    def cleanup_after_job(self) -> None:
        gc.collect()
        torch_mod = self._torch
        if torch_mod is not None and hasattr(torch_mod, "cuda") and torch_mod.cuda.is_available():
            torch_mod.cuda.empty_cache()

    @staticmethod
    def _trim_host_allocator(reason: str) -> bool:
        """Return freed glibc arenas to the cgroup after large model teardown."""
        gc.collect()
        try:
            libc = ctypes.CDLL(None)
            malloc_trim = libc.malloc_trim
            malloc_trim.argtypes = [ctypes.c_size_t]
            malloc_trim.restype = ctypes.c_int
            trimmed = bool(malloc_trim(0))
            print(
                f"[trellis2] host allocator trim after {reason}: {trimmed}",
                flush=True,
            )
            return trimmed
        except (AttributeError, OSError) as exc:
            print(
                f"[trellis2] host allocator trim unavailable after {reason}: {exc}",
                flush=True,
            )
            return False

    def _release_pipeline_before_scene_dna_scoring(self) -> None:
        """Keep SceneDNA scorers and TRELLIS checkpoints out of one cgroup peak.

        This is an opt-in resource-isolation path for repeated SceneDNA
        harmonization loops.  Moving the pipeline to CPU would exceed the host
        memory gate, so drop the cached pipeline and rebuild it after reference
        selection instead.  The default server behavior remains unchanged.
        """
        if not bool(
            getattr(
                self.args,
                "scene_dna_release_pipeline_before_scoring",
                False,
            )
        ):
            return
        with self._lock:
            if self._pipeline is None:
                return
            print(
                "[trellis2] releasing cached pipeline before SceneDNA scoring",
                flush=True,
            )
            self._pipeline = None
            gc.collect()
            torch_mod = self._torch
            if (
                torch_mod is not None
                and hasattr(torch_mod, "cuda")
                and torch_mod.cuda.is_available()
            ):
                torch_mod.cuda.empty_cache()

    def _pipeline_instance(self):
        if self._pipeline is not None:
            return self._pipeline, self._torch, self._o_voxel
        with self._lock:
            if self._pipeline is not None:
                return self._pipeline, self._torch, self._o_voxel
            os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
            os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
            if self.args.trellis_repo not in sys.path:
                sys.path.insert(0, self.args.trellis_repo)

            import torch
            import o_voxel
            from trellis2 import models as trellis2_models
            from trellis2.pipelines import Trellis2ImageTo3DPipeline
            from trellis2.pipelines import rembg as trellis2_rembg

            model_names_to_load = _trellis2_model_names_for_pipeline(str(self.args.pipeline_type))
            print(
                f"[trellis2] loading pipeline from {self.args.trellis_model} "
                f"for pipeline_type={self.args.pipeline_type}; models={model_names_to_load}",
                flush=True,
            )
            original_model_names = list(getattr(Trellis2ImageTo3DPipeline, "model_names_to_load", []))
            original_from_pretrained = trellis2_models.from_pretrained
            original_pipeline_birefnet = trellis2_rembg.BiRefNet

            def traced_from_pretrained(path: str, **kwargs: Any):
                start = time.time()
                print(f"[trellis2] loading checkpoint start: {path}", flush=True)
                model = original_from_pretrained(path, **kwargs)
                if self.args.trellis_low_vram is False:
                    # Loading every selected checkpoint on CPU before the final
                    # pipeline.to() creates a roughly 12 GiB host-RSS peak.  On
                    # a sufficiently large GPU, move each completed module
                    # immediately so CPU storage does not accumulate across
                    # checkpoints.  This is opt-in and leaves upstream/default
                    # low-VRAM behavior unchanged.
                    model.to(torch.device(self.args.device))
                    gc.collect()
                    print(
                        f"[trellis2] checkpoint moved to {self.args.device}: {path}",
                        flush=True,
                    )
                print(f"[trellis2] loading checkpoint done: {path} ({time.time() - start:.1f}s)", flush=True)
                return model

            Trellis2ImageTo3DPipeline.model_names_to_load = model_names_to_load
            trellis2_models.from_pretrained = traced_from_pretrained
            def local_pipeline_birefnet(**kwargs: Any):
                # TRELLIS.2's pipeline.json contains the upstream Hub name.  The
                # bridge already exposes --rmbg-model, so make that argument
                # authoritative as well during pipeline construction.  This
                # keeps offline runs from silently reaching for the network.
                kwargs["model_name"] = str(self.args.rmbg_model)
                return original_pipeline_birefnet(**kwargs)

            trellis2_rembg.BiRefNet = local_pipeline_birefnet
            try:
                pipeline = Trellis2ImageTo3DPipeline.from_pretrained(self.args.trellis_model)
            finally:
                Trellis2ImageTo3DPipeline.model_names_to_load = original_model_names
                trellis2_models.from_pretrained = original_from_pretrained
                trellis2_rembg.BiRefNet = original_pipeline_birefnet
            if self.args.trellis_low_vram is not None:
                pipeline.low_vram = bool(self.args.trellis_low_vram)
            print(
                f"[trellis2] pipeline low_vram={pipeline.low_vram}",
                flush=True,
            )
            pipeline.to(torch.device(self.args.device))
            self._pipeline = pipeline
            self._torch = torch
            self._o_voxel = o_voxel
            print(f"[trellis2] ready on {self.args.device}", flush=True)
        return self._pipeline, self._torch, self._o_voxel

    def _flux_background_phrases(self) -> list[str]:
        mode = str(self.args.flux_background_mode)
        if mode == "gray":
            return ["simple solid light gray background"]
        if mode == "white":
            return ["seamless pure white background (#FFFFFF)"]
        if mode == "contrast":
            return [
                "solid saturated cyan background",
                "solid saturated magenta background",
                "solid chroma green background",
                "solid dark neutral gray background",
            ]
        raise ValueError(f"Unsupported flux background mode: {mode}")

    def _white_base_prompt_clause(self, input_text: str, attempt: int = 0) -> str:
        text = str(input_text).lower()
        contains = lambda words: any(
            re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", text) for word in words
        )
        clauses = []
        if contains(("plant", "potted", "pot", "vase")):
            clauses.append("A real plant pot is allowed; no extra saucer")
        if contains(("chair", "sofa", "stool", "ottoman")):
            clauses.append(
                "Show visible separated supports or casters with white gaps beneath the body"
            )
        elif contains(("cabinet", "dresser", "nightstand", "wardrobe", "chest", "table", "bed")):
            clauses.append("Show furniture legs or bottom directly")
        if contains(("mirror",)):
            clauses.append("Mirror: glass and frame only")
        # "Light" alone also describes colors/materials and illumination.
        # Only explicit luminaire nouns may allow the object's lamp base.
        lamp_noun = re.search(
            r"(?<![a-z])(?:lamps?|lanterns?|"
            r"(?:floor|pendant|ceiling|table|desk|wall)[\s_-]+lights?)(?![a-z])",
            text,
        )
        if lamp_noun:
            clauses.append("A built-in lamp base is allowed")
        if attempt > 0:
            clauses.append("Retry without staging geometry")
        return ". ".join(clauses)

    def _compact_flux_object_text(self, input_text: str, max_words: int = 24) -> str:
        raw = " ".join(str(input_text).strip().split())
        if len(raw.split()) <= max_words:
            return raw
        clauses = [
            clause.strip(" .")
            for clause in re.split(r"[.!?]+", raw)
            if clause.strip(" .")
        ]
        selected = clauses[:3]
        for clause in clauses[3:]:
            lowered = clause.lower()
            if "complete composite asset includes" in lowered and clause not in selected:
                selected.append(clause)
        words = " ".join(selected).split()
        return " ".join(words[:max_words])

    def _compose_flux_prompt(self, input_text: str, background_phrase: str | None = None, attempt: int = 0) -> str:
        raw = self._compact_flux_object_text(input_text)
        if raw.lower().startswith("one "):
            raw = raw[4:]
        background = background_phrase or self._flux_background_phrases()[0]
        white_base_clause = self._white_base_prompt_clause(raw, attempt)
        support_clause = f" {white_base_clause}." if white_base_clause else ""
        prompt = (
            f"One isolated {raw}. {background}; centered full-object 3/4 view. "
            f"{support_clause} "
            "White void only: no horizon, floor plane, contact shadow, reflection, "
            "rug, platform, pedestal, plinth, base plate, props, text, or duplicate. "
            "The background must remain visually separate from the entire object silhouette."
        )
        return " ".join(prompt.split())

    def _source_white_background_report(
        self,
        rgba: np.ndarray,
        *,
        enforced: bool,
    ) -> dict[str, Any]:
        """Audit the removed source backdrop before hidden RGB is destroyed.

        FLUX cannot be expected to emit byte-exact #FFFFFF. This gate checks
        that pixels classified as background are uniformly near-white; the
        normalized preview below provides the byte-exact white contract.
        """

        alpha = rgba[:, :, 3]
        background = alpha <= int(getattr(self.args, "white_background_alpha_max", 8))
        pixels = rgba[:, :, :3][background].astype(np.float32)
        minimum_samples = max(64, int(round(alpha.size * 0.02)))
        limits = {
            "minimum_channel": float(
                getattr(self.args, "white_background_minimum_channel", 232.0)
            ),
            "maximum_chroma_range": float(
                getattr(self.args, "white_background_maximum_chroma_range", 18.0)
            ),
            "minimum_near_white_fraction": float(
                getattr(self.args, "white_background_minimum_fraction", 0.96)
            ),
            "maximum_median_deviation": float(
                getattr(self.args, "white_background_maximum_median_deviation", 18.0)
            ),
        }
        if len(pixels) < minimum_samples:
            diagnostic_reasons = ["insufficient_removed_background_samples"]
            return {
                "schema": "scene-v2-source-white-background/v1",
                "enforced": bool(enforced),
                "ok": not enforced,
                "conforms": False,
                "reasons": diagnostic_reasons if enforced else [],
                "diagnostic_reasons": diagnostic_reasons,
                "sample_count": int(len(pixels)),
                "minimum_sample_count": minimum_samples,
                "limits": limits,
            }

        chroma = pixels.max(axis=1) - pixels.min(axis=1)
        near_white = (
            (pixels.min(axis=1) >= limits["minimum_channel"])
            & (chroma <= limits["maximum_chroma_range"])
        )
        median = np.median(pixels, axis=0)
        deviations = np.linalg.norm(pixels - median[None, :], axis=1)
        near_white_fraction = float(np.mean(near_white))
        median_deviation = float(np.median(deviations))
        diagnostic_reasons: list[str] = []
        if near_white_fraction < limits["minimum_near_white_fraction"]:
            diagnostic_reasons.append("source_background_not_uniform_near_white")
        if median_deviation > limits["maximum_median_deviation"]:
            diagnostic_reasons.append("source_background_nonuniform")
        conforms = not diagnostic_reasons
        return {
            "schema": "scene-v2-source-white-background/v1",
            "enforced": bool(enforced),
            "ok": bool(conforms or not enforced),
            "conforms": conforms,
            "reasons": diagnostic_reasons if enforced else [],
            "diagnostic_reasons": diagnostic_reasons,
            "sample_count": int(len(pixels)),
            "minimum_sample_count": minimum_samples,
            "median_background_rgb": [round(float(value), 3) for value in median],
            "near_white_fraction": round(near_white_fraction, 6),
            "median_rgb_deviation": round(median_deviation, 4),
            "limits": limits,
        }

    def _exposed_support_background_gap_report(
        self,
        rgba: np.ndarray,
        object_text: str | None,
    ) -> dict[str, Any]:
        """Require visible background to rise between explicitly exposed legs.

        This colour-independent test catches a dark or textured connected
        staging slab that a white-only base detector cannot see.
        """

        required = self._requires_exposed_furniture_supports(object_text)
        report: dict[str, Any] = {
            "schema": "scene-v2-exposed-support-background-gap/v1",
            "required": required,
            "ok": True,
            "reasons": [],
        }
        if not required:
            return report
        foreground = rgba[:, :, 3] > int(getattr(self.args, "alpha_bbox_threshold", 24))
        ys, xs = np.nonzero(foreground)
        if not len(xs) or not len(ys):
            report["ok"] = False
            report["reasons"] = ["no_foreground_for_support_gap"]
            return report
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        inset = int(
            round(
                width
                * float(
                    getattr(self.args, "support_gap_horizontal_inset_ratio", 0.10)
                )
            )
        )
        inner_x0 = min(x1 - 1, x0 + inset)
        inner_x1 = max(inner_x0 + 1, x1 - inset)
        minimum_depth_ratio = float(
            getattr(self.args, "support_gap_minimum_depth_ratio", 0.11)
        )
        minimum_open_fraction = float(
            getattr(self.args, "support_gap_minimum_open_column_fraction", 0.30)
        )
        minimum_depth = max(2, int(np.ceil(height * minimum_depth_ratio)))
        crop = foreground[y0:y1, inner_x0:inner_x1]
        open_depths: list[int] = []
        for column in range(crop.shape[1]):
            occupied = np.nonzero(crop[:, column])[0]
            open_depths.append(
                height
                if len(occupied) == 0
                else max(0, height - 1 - int(occupied[-1]))
            )
        qualifying = np.asarray(open_depths, dtype=np.int32) >= minimum_depth
        open_fraction = float(np.mean(qualifying)) if len(qualifying) else 0.0
        if open_fraction < minimum_open_fraction:
            report["ok"] = False
            report["reasons"].append("exposed_support_background_gap_missing")
        report.update(
            {
                "foreground_bbox": [x0, y0, x1, y1],
                "evaluated_horizontal_range": [inner_x0, inner_x1],
                "minimum_gap_depth_ratio": minimum_depth_ratio,
                "minimum_gap_depth_pixels": minimum_depth,
                "minimum_open_column_fraction": minimum_open_fraction,
                "open_column_fraction": round(open_fraction, 6),
                "median_bottom_open_depth_ratio": (
                    round(float(np.median(open_depths)) / float(height), 6)
                    if open_depths
                    else 0.0
                ),
            }
        )
        return report

    def _center_foreground_on_transparent_canvas(self, rgba: np.ndarray) -> np.ndarray:
        alpha = rgba[:, :, 3]
        ys, xs = np.nonzero(alpha > int(self.args.alpha_bbox_threshold))
        if len(xs) == 0 or len(ys) == 0:
            return rgba

        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        crop = rgba[y0:y1, x0:x1]
        crop_h, crop_w = crop.shape[:2]
        if crop_h <= 0 or crop_w <= 0:
            return rgba

        h, w = rgba.shape[:2]
        target_side = min(h, w)
        max_content = max(1, int(target_side * float(self.args.alpha_content_scale)))
        scale = min(1.0, max_content / float(max(crop_w, crop_h)))
        if scale < 0.999:
            resized = Image.fromarray(crop, mode="RGBA").resize(
                (max(1, int(crop_w * scale)), max(1, int(crop_h * scale))),
                Image.Resampling.LANCZOS,
            )
            crop = np.array(resized, dtype=np.uint8)
            crop_h, crop_w = crop.shape[:2]

        canvas = np.zeros_like(rgba)
        paste_x = (w - crop_w) // 2
        paste_y = (h - crop_h) // 2
        canvas[paste_y : paste_y + crop_h, paste_x : paste_x + crop_w] = crop
        return canvas

    def _wait_for_flux_image(self, prompt: str, seed: int, job_id: str) -> Path:
        image_path = Path(self.args.output_dir) / "reference_images" / f"{job_id}.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        flux_payload: dict[str, Any] = {
            "prompt": prompt,
            "seed": seed,
            "width": self.args.flux_width,
            "height": self.args.flux_height,
            "steps": self.args.flux_steps,
            "guidance_scale": self.args.flux_guidance_scale,
        }
        if self.args.flux_max_sequence_length is not None:
            flux_payload["max_sequence_length"] = self.args.flux_max_sequence_length

        status, payload = post_json(
            f"{self.args.flux_server_url.rstrip('/')}/generate",
            flux_payload,
            # The FLUX worker can briefly hold the interpreter while a prior
            # image is finishing.  Give the accepted-job response enough time
            # to arrive; retrying POST would risk creating a duplicate job.
            timeout=min(120.0, max(20.0, float(self.args.flux_timeout))),
        )
        if status != 202:
            raise RuntimeError(f"Flux server returned unexpected status: {status}")
        flux_job_id = payload.get("job_id")
        if not flux_job_id:
            raise RuntimeError("Flux server did not return job_id")

        deadline = time.time() + self.args.flux_timeout
        while time.time() < deadline:
            try:
                status, body, content_type = get_bytes(
                    f"{self.args.flux_server_url.rstrip('/')}/job/{flux_job_id}",
                    timeout=60.0,
                )
            except (TimeoutError, URLError, ConnectionError):
                # A slow individual poll is not a failed generation.  Keep the
                # frozen batch alive until the explicit FLUX batch deadline.
                time.sleep(1.0)
                continue
            if status == 200:
                image_path.write_bytes(body)
                return image_path
            if status == 500:
                raise RuntimeError(body.decode("utf-8", errors="replace"))
            if status != 202:
                raise RuntimeError(f"Flux job returned unexpected status {status} ({content_type})")
            time.sleep(1.0)
        raise TimeoutError(f"Flux job timed out after {self.args.flux_timeout}s")

    def _image_provider(self, payload: dict[str, Any]) -> str:
        provider = str(payload.get("image_provider", getattr(self.args, "image_provider", "builtin_imagegen")))
        if provider not in BRIDGE_IMAGE_PROVIDERS:
            raise ValueError(f"Unsupported image provider: {provider}")
        if provider != "builtin_imagegen" and getattr(self.args, "flux_profile", provider) != provider:
            raise ValueError("Selected FLUX provider does not match the configured model profile")
        return provider

    def image_provider_contract(self, provider: str) -> dict[str, Any]:
        contract = {
            "schema": "scene-image-provider-contract/v1",
            "provider": provider,
            "prompt_template_version": "isolated-white-v2-light-noun",
            "background_mode": self.args.flux_background_mode,
            "retry_count": self.args.flux_retry_count,
            "native_alpha_normalization": json.loads(json.dumps(NATIVE_ALPHA_POLICY)),
        }
        if provider == "builtin_imagegen":
            contract.update({
                "transport": "codex_tool_spool/v1", "requested_model": None,
                "backend_model_id": None, "model_identity_status": "unverified",
                "seed_supported": False, "size_control_supported": False,
            })
        else:
            contract.update({
                "transport": "flux_http/v1", "requested_model": self.args.flux_profile,
                "width": self.args.flux_width, "height": self.args.flux_height,
                "steps": self.args.flux_steps, "guidance_scale": self.args.flux_guidance_scale,
                "max_sequence_length": self.args.flux_max_sequence_length,
            })
        return contract

    def _wait_for_builtin_image(
        self, prompt: str, job_id: str, *, parent_job_id: str, specification: str, attempt: int
    ) -> tuple[Path, dict[str, Any]]:
        """Wait for the real Codex executor; keep accepted handles on disk."""
        base = str(self.args.builtin_imagegen_url).rstrip("/")
        timeout = float(self.args.builtin_imagegen_timeout)
        root = self._persistent_evidence_root() / "provider_requests"
        root.mkdir(parents=True, exist_ok=True)
        handle_path = root / f"{job_id}.json"
        request_payload = {
            "prompt": prompt,
            "provider": "builtin_imagegen",
            "request_id": job_id,
            "upstream_job_id": parent_job_id,
            "specification": specification,
            "attempt": attempt,
            "requested_model": None,
        }
        if handle_path.is_file():
            accepted = json.loads(handle_path.read_text(encoding="utf-8"))
            if accepted.get("request") != request_payload or accepted.get("provider_url") != base:
                raise ValueError("Persisted image provider request does not match this attempt")
        else:
            status, response = post_json(base + "/generate", request_payload, timeout=30.0)
            if status != 202 or not response.get("job_id"):
                raise RuntimeError(f"Builtin provider rejected request: {status} {response}")
            accepted = {"request": request_payload, "provider_url": base, **response}
            partial = handle_path.with_suffix(".json.partial")
            partial.write_text(json.dumps(accepted, indent=2), encoding="utf-8")
            partial.replace(handle_path)
        provider_job_id = str(accepted["job_id"])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status, body, content_type = get_bytes(base + f"/job/{provider_job_id}", timeout=30.0)
            except (TimeoutError, URLError, ConnectionError):
                time.sleep(1.0)
                continue
            if status == 200:
                if not content_type.startswith("image/"):
                    raise ValueError("Builtin provider returned a non-image completion")
                meta_status, meta_bytes, _ = get_bytes(base + f"/job/{provider_job_id}/metadata", timeout=30.0)
                if meta_status != 200:
                    raise ValueError("Builtin provider completed without metadata")
                metadata = json.loads(meta_bytes)
                image_hash = hashlib.sha256(body).hexdigest()
                if metadata.get("provider") != "builtin_imagegen" or metadata.get("job_id") != provider_job_id:
                    raise ValueError("Builtin image metadata belongs to another provider/job")
                if metadata.get("image_sha256") != image_hash:
                    raise ValueError("Builtin image hash does not match provider metadata")
                if metadata.get("prompt_sha256") != hashlib.sha256(prompt.encode("utf-8")).hexdigest():
                    raise ValueError("Builtin image prompt binding mismatch")
                if metadata.get("request_sha256") != accepted.get("request_sha256"):
                    raise ValueError("Builtin image request binding mismatch")
                if metadata.get("request_id") != job_id or metadata.get("upstream_job_id") != parent_job_id:
                    raise ValueError("Builtin image reference binding mismatch")
                image_path = root / f"{job_id}.png"
                partial = image_path.with_suffix(".png.partial")
                partial.write_bytes(body)
                with Image.open(partial) as candidate:
                    candidate.verify()
                partial.replace(image_path)
                return image_path, metadata
            if status != 202:
                raise RuntimeError(f"Builtin image job {provider_job_id} failed: {status} {body[:500]!r}")
            time.sleep(1.0)
        raise TimeoutError(f"waiting_for_image_provider: {provider_job_id}; resume handle {handle_path}")

    def _reference_candidates_for_payload(self, payload: dict[str, Any], job_id: str) -> Iterable[dict[str, Any]]:
        provider = self._image_provider(payload)
        replay = payload.get("replay_reference_evidence")
        if replay is not None:
            from sage.experiments.codex_trellis_scene_v2.asset_source_policy import validate_builtin_raw_artifact_evidence
            if provider != "builtin_imagegen" or not isinstance(replay, dict):
                raise ValueError("Raw replay requires builtin image evidence")
            manifest_record = replay.get("manifest") or {}
            manifest_path = Path(str(manifest_record.get("path") or ""))
            if self._evidence_file_record(manifest_path) != manifest_record:
                raise ValueError("Raw replay manifest binding mismatch")
            original = json.loads(manifest_path.read_text(encoding="utf-8"))
            failures = validate_builtin_raw_artifact_evidence({**original, "manifest": manifest_record})
            if failures:
                raise ValueError(f"Raw replay provenance rejected: {failures}")
            raw = original["files"]["source_rgb"]
            if replay.get("reference") != raw or self._evidence_file_record(Path(raw["path"])) != raw:
                raise ValueError("Raw replay must select the original tool image")
            if job_id in {original.get("parent_job_id"), original.get("reference_job_id")}:
                raise ValueError("Raw replay requires a new job and attempt")
            direct = payload.get("reference_image_path") or payload.get("input_image_path")
            if direct and Path(str(direct)).resolve() != Path(raw["path"]).resolve():
                raise ValueError("Direct reference conflicts with raw replay")
            yield {
                "source_image_path": Path(raw["path"]), "reference_job_id": job_id,
                "generated": False, "attempt": 0, "prompt": None, "seed": None,
                "image_provider": provider,
                "image_provider_metadata": original["image_provider_metadata"],
                "replay_reference_evidence": replay,
                "enforce_white_background": True,
            }
            return
        direct = payload.get("reference_image_path") or payload.get("input_image_path")
        if direct:
            path = Path(str(direct))
            if not path.exists():
                raise FileNotFoundError(f"reference image not found: {path}")
            inherited_metadata = None
            upstream = self._persisted_generated_reference_provenance(path)
            if upstream:
                upstream_manifest = json.loads(Path(upstream["manifest"]["path"]).read_text(encoding="utf-8"))
                inherited_provider = upstream_manifest.get("image_provider", "flux1-schnell")
                if inherited_provider != provider:
                    raise ValueError("Direct reference provider conflicts with selected route")
                path = Path(upstream_manifest["files"]["source_rgb"]["path"])
                if inherited_provider == "builtin_imagegen":
                    inherited_metadata = upstream_manifest["image_provider_metadata"]
            yield {
                "source_image_path": path,
                "reference_job_id": job_id,
                "generated": False,
                "attempt": 0,
                "prompt": None,
                "seed": payload.get("seed"),
                "image_provider": provider,
                "image_provider_metadata": inherited_metadata,
                "enforce_white_background": upstream is not None,
            }
            return
        input_text = str(payload.get("input_text") or payload.get("prompt") or "").strip()
        if not input_text:
            raise ValueError("Missing input_text")
        backgrounds = self._flux_background_phrases()
        scene_dna_count = self._scene_dna_candidate_count(payload)
        attempts = (
            scene_dna_count
            if scene_dna_count > 1
            else max(1, int(self.args.flux_retry_count) + 1)
        )
        base_seed = int(payload.get("seed", 1))
        for attempt in range(attempts):
            background = backgrounds[attempt % len(backgrounds)]
            prompt = self._compose_flux_prompt(input_text, background, attempt)
            attempt_seed = base_seed + attempt * 9973
            reference_job_id = job_id if attempt == 0 else f"{job_id}_retry{attempt:02d}"
            provider_metadata = None
            if provider == "builtin_imagegen":
                source_image_path, provider_metadata = self._wait_for_builtin_image(
                    prompt, reference_job_id, parent_job_id=job_id, specification=input_text, attempt=attempt
                )
            else:
                source_image_path = self._wait_for_flux_image(prompt, attempt_seed, reference_job_id)
            yield {
                "source_image_path": source_image_path,
                "reference_job_id": reference_job_id,
                "generated": True,
                "attempt": attempt,
                "prompt": prompt,
                "background": background,
                "seed": attempt_seed if provider != "builtin_imagegen" else None,
                "requested_seed": attempt_seed,
                "image_provider": provider,
                "image_provider_metadata": provider_metadata,
            }
            if not self.args.alpha_quality_check and scene_dna_count <= 1:
                break

    def _scene_dna_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        scene_dna = payload.get("scene_dna")
        if not isinstance(scene_dna, dict) or not scene_dna.get("contract_hash"):
            return None
        return scene_dna

    def _scene_dna_candidate_count(self, payload: dict[str, Any]) -> int:
        if payload.get("reference_image_path") or payload.get("input_image_path"):
            return 1
        scene_dna = self._scene_dna_payload(payload)
        if scene_dna is None:
            return 1
        funnel = scene_dna.get("candidate_funnel")
        funnel = funnel if isinstance(funnel, dict) else {}
        requested = payload.get(
            "scene_dna_candidate_count",
            funnel.get("isolated_2d_candidates", 1),
        )
        return max(1, min(8, int(requested or 1)))

    def _scene_dna_visual_candidate_score(
        self,
        prepared_image_path: Path,
        alpha_metadata: dict[str, Any],
        scene_dna: dict[str, Any],
    ) -> dict[str, Any]:
        """Score real foreground pixels without treating this as semantic/VLM proof."""

        rgba = np.array(Image.open(prepared_image_path).convert("RGBA"), dtype=np.uint8)
        foreground = rgba[:, :, 3] > int(getattr(self.args, "alpha_bbox_threshold", 24))
        pixels = rgba[:, :, :3][foreground].astype(np.float32)
        alpha_quality = alpha_metadata.get("alpha_quality", {})
        alpha_score = max(
            0.0,
            min(1.0, float(alpha_quality.get("score", 0.0))),
        )
        if pixels.size == 0:
            return {
                "score": 0.0,
                "alpha_structure_score": alpha_score,
                "palette_score": 0.0,
                "temperature_score": 0.0,
                "detail_score": 0.0,
                "reason": "empty_foreground",
                "semantic_embedding_evaluated": False,
            }
        if len(pixels) > 50_000:
            pixels = pixels[:: max(1, len(pixels) // 50_000)][:50_000]

        palette_rgb: dict[str, tuple[int, int, int]] = {
            "white": (238, 238, 232),
            "black": (32, 32, 32),
            "beige": (210, 190, 158),
            "gray": (135, 135, 135),
            "blue": (55, 92, 155),
            "green": (80, 125, 82),
            "red": (165, 58, 48),
            "oak": (181, 132, 78),
            "walnut": (92, 58, 38),
            "wood": (164, 112, 67),
            "brass": (184, 145, 62),
        }
        global_tags = {
            str(item).strip().lower()
            for item in scene_dna.get("global_tags", [])
            if str(item).strip()
        }
        individuality_tags = {
            str(item).strip().lower()
            for item in scene_dna.get("individuality_tags", [])
            if str(item).strip()
        }
        desired_tags = global_tags | individuality_tags
        local_palette_tags = individuality_tags & set(palette_rgb)
        palette_target_tags = local_palette_tags or (desired_tags & set(palette_rgb))
        palette_scores: dict[str, float] = {}
        max_rgb_distance = float(np.sqrt(3.0) * 255.0)
        for tag in sorted(palette_target_tags):
            target = np.array(palette_rgb[tag], dtype=np.float32)
            distances = np.linalg.norm(pixels - target, axis=1)
            representative_distance = float(np.percentile(distances, 20.0))
            palette_scores[tag] = round(
                max(0.0, min(1.0, 1.0 - representative_distance / max_rgb_distance)),
                6,
            )
        palette_score = max(palette_scores.values(), default=0.5)

        mean_rgb = pixels.mean(axis=0)
        warmth_index = float((mean_rgb[0] - mean_rgb[2]) / 255.0)
        if "warm" in desired_tags and "cool" not in desired_tags:
            temperature_score = max(0.0, min(1.0, 0.5 + warmth_index))
            temperature_target = "warm"
        elif "cool" in desired_tags and "warm" not in desired_tags:
            temperature_score = max(0.0, min(1.0, 0.5 - warmth_index))
            temperature_target = "cool"
        else:
            temperature_score = 0.5
            temperature_target = "unspecified"

        gray = (
            rgba[:, :, 0].astype(np.float32) * 0.299
            + rgba[:, :, 1].astype(np.float32) * 0.587
            + rgba[:, :, 2].astype(np.float32) * 0.114
        )
        horizontal_valid = foreground[:, 1:] & foreground[:, :-1]
        vertical_valid = foreground[1:, :] & foreground[:-1, :]
        horizontal_edges = np.abs(gray[:, 1:] - gray[:, :-1]) > 18.0
        vertical_edges = np.abs(gray[1:, :] - gray[:-1, :]) > 18.0
        valid_count = int(np.count_nonzero(horizontal_valid)) + int(
            np.count_nonzero(vertical_valid)
        )
        edge_count = int(np.count_nonzero(horizontal_edges & horizontal_valid)) + int(
            np.count_nonzero(vertical_edges & vertical_valid)
        )
        edge_density = float(edge_count) / float(max(1, valid_count))
        target_edge_density = 0.08
        detail_score = max(
            0.0,
            min(1.0, 1.0 - abs(edge_density - target_edge_density) / 0.18),
        )
        score = (
            0.55 * alpha_score
            + 0.25 * palette_score
            + 0.10 * temperature_score
            + 0.10 * detail_score
        )
        legacy_report = {
            "score": round(score, 6),
            "alpha_structure_score": round(alpha_score, 6),
            "palette_score": round(palette_score, 6),
            "palette_tag_scores": palette_scores,
            "palette_target_source": (
                "object_individuality" if local_palette_tags else "global_profile"
            ),
            "temperature_score": round(temperature_score, 6),
            "temperature_target": temperature_target,
            "warmth_index": round(warmth_index, 6),
            "detail_score": round(detail_score, 6),
            "edge_density": round(edge_density, 6),
            "weights": {
                "alpha_structure": 0.55,
                "palette": 0.25,
                "temperature": 0.10,
                "detail": 0.10,
            },
            "foreground_pixel_count": int(len(pixels)),
            "pixel_feature_evaluated": True,
            "semantic_embedding_evaluated": False,
            "limitations": "pixel palette/detail score; not semantic style or category verification",
        }
        semantic_form_contract = scene_dna.get("semantic_form_contract")
        semantic_form_contract = (
            semantic_form_contract
            if isinstance(semantic_form_contract, dict)
            else {}
        )
        vnext_enabled = bool(
            getattr(self.args, "scene_dna_vnext_selector", False)
        )
        if not bool(getattr(self.args, "scene_dna_form_scoring", False)) and not vnext_enabled:
            return legacy_report

        form_report = score_form_contract(
            prepared_image_path,
            semantic_form_contract,
            alpha_threshold=int(getattr(self.args, "alpha_bbox_threshold", 24)),
        )
        semantic_report: dict[str, Any] | None = None
        semantic_mode = str(
            getattr(self.args, "scene_dna_semantic_scoring", "off")
        )
        if semantic_mode != "off":
            try:
                with self._semantic_scorer_lock:
                    if self._semantic_scorer is None:
                        self._semantic_scorer = Siglip2SemanticScorer(
                            str(self.args.scene_dna_semantic_model),
                            device=str(self.args.scene_dna_semantic_device),
                        )
                    semantic_report = self._semantic_scorer.score(
                        prepared_image_path, semantic_form_contract
                    )
            except Exception as exc:
                if semantic_mode == "required":
                    raise
                semantic_report = {
                    "evaluated": False,
                    "score": None,
                    "error": f"{type(exc).__name__}: {exc}",
                    "reason": "optional_semantic_scorer_unavailable",
                }
        anchor_report: dict[str, Any] | None = None
        anchor_manifest_path = str(
            getattr(self.args, "scene_dna_anchor_manifest", "") or ""
        )
        if anchor_manifest_path:
            try:
                with self._semantic_scorer_lock:
                    if self._anchor_scorer is None:
                        anchor_manifest = json.loads(
                            Path(anchor_manifest_path).read_text(encoding="utf-8")
                        )
                        self._anchor_scorer = DinoV3PrototypeScorer(
                            str(self.args.scene_dna_anchor_model),
                            anchor_manifest,
                            device=str(self.args.scene_dna_anchor_device),
                        )
                    anchor_report = self._anchor_scorer.score(
                        prepared_image_path, semantic_form_contract
                    )
            except Exception as exc:
                anchor_report = {
                    "evaluated": False,
                    "score": None,
                    "error": f"{type(exc).__name__}: {exc}",
                    "reason": "optional_anchor_scorer_unavailable",
                }
        combined = combine_semantic_form_style_scores(
            pixel_style_score=(
                0.625 * palette_score
                + 0.25 * temperature_score
                + 0.125 * detail_score
            ),
            form_report=form_report,
            semantic_report=semantic_report,
            anchor_similarity_score=(
                float(anchor_report["score"])
                if isinstance(anchor_report, dict)
                and anchor_report.get("evaluated")
                and anchor_report.get("score") is not None
                else None
            ),
        )
        generability_report = assess_2d_generability(
            prepared_image_path,
            alpha_metadata=alpha_metadata,
            semantic_report=semantic_report,
            form_report=form_report,
            alpha_threshold=int(getattr(self.args, "alpha_bbox_threshold", 24)),
        )
        return {
            **legacy_report,
            "score": combined["score"],
            "selection_strategy": "semantic_form_style_v1",
            "legacy_pixel_score": legacy_report["score"],
            "semantic": semantic_report,
            "form": form_report,
            "anchor_similarity": anchor_report,
            "generability": generability_report,
            "combined": combined,
            "semantic_embedding_evaluated": combined[
                "semantic_embedding_evaluated"
            ],
            "limitations": (
                "experimental frozen semantic/form/style ranking; blind-label "
                "calibration still required"
            ),
        }

    def _select_scene_dna_reference_attempt(
        self,
        reference_attempts: list[dict[str, Any]],
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self._release_pipeline_before_scene_dna_scoring()
        scene_dna = self._scene_dna_payload(payload)
        if scene_dna is None:
            raise ValueError("SceneDNA reference selection requires a SceneDNA payload")
        usable = [item for item in reference_attempts if item.get("prepared_image_path")]
        if not usable:
            raise RuntimeError("No usable reference image was prepared")
        for item in usable:
            try:
                item["scene_dna_candidate_score"] = self._scene_dna_visual_candidate_score(
                    Path(str(item["prepared_image_path"])),
                    item.get("alpha_metadata", {}),
                    scene_dna,
                )
            except Exception as exc:
                item["scene_dna_candidate_score"] = {
                    "score": 0.0,
                    "error": f"{type(exc).__name__}: {exc}",
                    "semantic_embedding_evaluated": False,
                }
        eligible = list(usable)
        vnext_enabled = bool(
            getattr(self.args, "scene_dna_vnext_selector", False)
        )
        if bool(getattr(self.args, "white_base_require_clean", True)):
            clean = [item for item in eligible if not self._attempt_has_white_base_violation(item)]
            if not clean:
                raise RuntimeError("All SceneDNA reference candidates failed white-base QA")
            eligible = clean
        if bool(getattr(self.args, "background_isolation_require_clean", False)):
            isolated = [
                item
                for item in eligible
                if not self._attempt_has_background_isolation_violation(item)
            ]
            if not isolated:
                raise RuntimeError(
                    "All SceneDNA reference candidates failed white-background isolation QA"
                )
            eligible = isolated
        alpha_ok = [item for item in eligible if bool(item.get("alpha_quality_ok"))]
        if alpha_ok:
            eligible = alpha_ok
        elif bool(getattr(self.args, "alpha_require_quality", False)):
            raise RuntimeError("All SceneDNA reference candidates failed required alpha QA")
        hygiene_eligible = list(eligible)
        form_gate_eligible = [
            item
            for item in eligible
            if bool(
                item.get("scene_dna_candidate_score", {})
                .get("form", {})
                .get("gate_passed")
            )
        ]
        if bool(getattr(self.args, "scene_dna_form_scoring", False)):
            current_eligible = list(form_gate_eligible)
        else:
            current_eligible = list(hygiene_eligible)
        if not current_eligible and bool(
            getattr(self.args, "scene_dna_form_scoring", False)
        ) and not vnext_enabled:
            raise RuntimeError(
                "All SceneDNA reference candidates failed the required form contract"
            )
        # vNext deliberately treats the old single-view form profile as soft
        # evidence.  Image hygiene and semantic identity remain hard gates.
        eligible = list(hygiene_eligible if vnext_enabled else current_eligible)
        semantic_gate_eligible = [
            item
            for item in eligible
            if bool(
                (
                    item.get("scene_dna_candidate_score", {}).get("semantic")
                    or {}
                ).get("gate_passed")
            )
        ]
        if semantic_gate_eligible:
            eligible = semantic_gate_eligible
        elif str(getattr(self.args, "scene_dna_semantic_scoring", "off")) == "required":
            raise RuntimeError(
                "All SceneDNA reference candidates failed the required semantic contract"
            )
        current_semantic_eligible = [
            item
            for item in current_eligible
            if str(getattr(self.args, "scene_dna_semantic_scoring", "off"))
            != "required"
            or bool(
                (
                    item.get("scene_dna_candidate_score", {}).get("semantic")
                    or {}
                ).get("gate_passed")
            )
        ]
        current_selector_rejected = not current_semantic_eligible
        current_ranking_pool = current_semantic_eligible or eligible
        combined_selected = max(
            current_ranking_pool,
            key=lambda item: (
                float(item.get("scene_dna_candidate_score", {}).get("score", -1.0)),
                float(
                    item.get("alpha_metadata", {})
                    .get("alpha_quality", {})
                    .get("score", -1.0)
                ),
                -int(item.get("attempt", 0)),
            ),
        )
        legacy_control = max(
            current_ranking_pool,
            key=lambda item: (
                float(
                    item.get("scene_dna_candidate_score", {}).get(
                        "legacy_pixel_score", -1.0
                    )
                ),
                float(
                    item.get("alpha_metadata", {})
                    .get("alpha_quality", {})
                    .get("score", -1.0)
                ),
                -int(item.get("attempt", 0)),
            ),
        )
        form_guard_enabled = bool(
            getattr(self.args, "scene_dna_form_improvement_guard", False)
        )
        if form_guard_enabled and vnext_enabled:
            raise ValueError(
                "SceneDNA vNext selector and legacy form guard are mutually exclusive"
            )
        vnext_selected, vnext_selection = select_vnext_candidate(eligible)
        selection_guard: dict[str, Any] = {
            "schema": "scene_dna_form_improvement_guard_v1",
            "enabled": False,
            "decision": "not_applied",
            "category_specific_branching": False,
        }
        selected = combined_selected
        if vnext_enabled:
            if vnext_selection["all_candidates_failed_generability_gate"]:
                raise RuntimeError(
                    "All SceneDNA reference candidates failed the vNext generability gate"
                )
            selected = vnext_selected
        elif form_guard_enabled and combined_selected is not legacy_control:
            selection_guard = form_improvement_guard(
                combined_selected.get("scene_dna_candidate_score", {}),
                legacy_control.get("scene_dna_candidate_score", {}),
                minimum_form_improvement=float(
                    getattr(
                        self.args,
                        "scene_dna_minimum_form_improvement",
                        0.08,
                    )
                ),
            )
            if not selection_guard["accepted_proposed_selection"]:
                selected = legacy_control
        elif form_guard_enabled:
            selection_guard = {
                "schema": "scene_dna_form_improvement_guard_v1",
                "enabled": True,
                "accepted_proposed_selection": True,
                "decision": "combined_and_legacy_select_same_candidate",
                "minimum_form_improvement": float(
                    getattr(
                        self.args,
                        "scene_dna_minimum_form_improvement",
                        0.08,
                    )
                ),
                "category_specific_branching": False,
                "calibration_status": "development_only_requires_heldout_validation",
            }
        funnel = scene_dna.get("candidate_funnel")
        funnel = funnel if isinstance(funnel, dict) else {}
        ranking = sorted(
            usable,
            key=lambda item: float(
                item.get("scene_dna_candidate_score", {}).get("score", -1.0)
            ),
            reverse=True,
        )
        eligible_ranking = [item for item in ranking if item in eligible]
        semantic_ranking = sorted(
            [
                item
                for item in eligible
                if (
                    item.get("scene_dna_candidate_score", {}).get("semantic")
                    or {}
                ).get("evaluated")
            ],
            key=lambda item: float(
                item["scene_dna_candidate_score"]["semantic"].get("score", -1.0)
            ),
            reverse=True,
        )
        form_ranking = sorted(
            [
                item
                for item in eligible
                if item.get("scene_dna_candidate_score", {})
                .get("form", {})
                .get("evaluated")
            ],
            key=lambda item: float(
                item["scene_dna_candidate_score"]["form"].get("score", -1.0)
            ),
            reverse=True,
        )
        scorer_conflict = bool(
            semantic_ranking
            and form_ranking
            and semantic_ranking[0] is not form_ranking[0]
        )
        margin_threshold = float(
            getattr(self.args, "scene_dna_uncertainty_margin", 0.03)
        )
        uncertainty = selection_uncertainty(
            [
                float(item.get("scene_dna_candidate_score", {}).get("score", 0.0))
                for item in eligible_ranking
            ],
            margin_threshold=margin_threshold,
            scorer_conflict=scorer_conflict,
        )
        maximum_promoted = max(
            1, int(funnel.get("max_candidates_promoted_to_trellis2", 2))
        )
        promotion_count = min(
            len(eligible_ranking),
            maximum_promoted,
            int(uncertainty["recommended_promotion_count"]),
        )
        promotion_order = [selected] + [
            item for item in eligible_ranking if item is not selected
        ]
        promoted = promotion_order[:promotion_count]
        report = {
            "schema": "scene_dna_2d_candidate_selection_v1",
            "contract_hash": scene_dna.get("contract_hash"),
            "requested_candidate_count": self._scene_dna_candidate_count(payload),
            "generated_candidate_count": len(reference_attempts),
            "usable_candidate_count": len(usable),
            "eligible_candidate_count": len(eligible),
            "max_candidates_promoted_to_trellis2": int(
                funnel.get("max_candidates_promoted_to_trellis2", 2)
            ),
            "actual_candidates_promoted_to_trellis2": promotion_count,
            "promoted_reference_job_ids": [
                item.get("reference_job_id") for item in promoted
            ],
            "promoted_reference_image_paths": [
                item.get("prepared_image_path") for item in promoted
            ],
            "uncertainty": uncertainty,
            "selected_reference_job_id": selected.get("reference_job_id"),
            "combined_selector_reference_job_id": combined_selected.get(
                "reference_job_id"
            ) if not current_selector_rejected else None,
            "current_selector_batch_rejected": current_selector_rejected,
            "current_selector_hard_eligible_candidate_count": len(
                current_semantic_eligible
            ),
            "vnext_selector_reference_job_id": vnext_selected.get(
                "reference_job_id"
            ),
            "legacy_control_reference_job_id": legacy_control.get(
                "reference_job_id"
            ) if not current_selector_rejected else None,
            "selection_guard": selection_guard,
            "vnext_selection": {
                **vnext_selection,
                "enabled": vnext_enabled,
                "decision": (
                    vnext_selection["decision"]
                    if vnext_enabled
                    else "preview_only_default_off"
                ),
            },
            "ranking": [
                {
                    "rank": rank,
                    "reference_job_id": item.get("reference_job_id"),
                    "attempt": item.get("attempt"),
                    "alpha_quality_ok": bool(item.get("alpha_quality_ok")),
                    "eligible": item in eligible,
                    "score": item.get("scene_dna_candidate_score"),
                }
                for rank, item in enumerate(ranking, start=1)
            ],
            "hard_gates": [
                "prepared_rgba_exists",
                "white_base_clean",
                "alpha_quality_if_available",
                *(
                    ["form_contract"]
                    if bool(getattr(self.args, "scene_dna_form_scoring", False))
                    else []
                ),
                *(
                    ["semantic_contract"]
                    if str(getattr(self.args, "scene_dna_semantic_scoring", "off"))
                    == "required"
                    else []
                ),
                *(["vnext_generability"] if vnext_enabled else []),
            ],
            "selection_method": (
                "hard_QA_then_opt_in_vnext_balanced_generability"
                if vnext_enabled
                else "hard_QA_then_opt_in_form_improvement_guard"
                if form_guard_enabled
                else "hard_QA_then_semantic_form_anchor_pixel_ranking"
                if bool(getattr(self.args, "scene_dna_form_scoring", False))
                else "hard_QA_then_weighted_pixel_palette_temperature_detail"
            ),
            "semantic_embedding_evaluated": any(
                bool(
                    item.get("scene_dna_candidate_score", {}).get(
                        "semantic_embedding_evaluated"
                    )
                )
                for item in usable
            ),
            "form_contract_evaluated": any(
                bool(
                    item.get("scene_dna_candidate_score", {})
                    .get("form", {})
                    .get("evaluated")
                )
                for item in usable
            ),
        }
        if bool(getattr(self.args, "scene_dna_unload_scorers", True)):
            with self._semantic_scorer_lock:
                for scorer in (self._semantic_scorer, self._anchor_scorer):
                    if scorer is not None:
                        scorer.close()
                self._semantic_scorer = None
                self._anchor_scorer = None
            self._trim_host_allocator("SceneDNA scorer unload")
            torch_mod = self._torch
            if (
                torch_mod is not None
                and hasattr(torch_mod, "cuda")
                and torch_mod.cuda.is_available()
            ):
                torch_mod.cuda.empty_cache()
        return selected, report

    def _white_base_policy_notes(self, object_text: str | None = None) -> dict[str, Any]:
        text = str(object_text or "").lower()
        legal = [
            "white or cream material that is part of the object itself",
            "white fabric, bedding, pillows, lampshades, ceramic lamp bodies, mirror glass, cabinet highlights, handles, labels, or small reflections",
            "a plant's real pot or vase, including a white pot, when it is the actual container",
        ]
        illegal = [
            "extra white circular/oval disc under the object",
            "product-photo display platform, pedestal, plinth, base plate, floor patch, shadow catcher, or support surface",
            "white stage/table/floor geometry that is not part of the named object",
            "a saucer-like platform under a pot, cabinet, lamp, mirror, or furniture legs",
        ]
        object_notes: list[str] = []
        if any(word in text for word in ("plant", "potted", "pot", "vase")):
            object_notes.append("For plants, a white pot is legal; an extra white saucer/platform under the pot is illegal.")
        if any(word in text for word in ("lamp", "lantern", "light")):
            object_notes.append("For lamps, a shade/pole/tripod/built-in lamp base is legal; a separate white floor disc is illegal.")
        if "mirror" in text:
            object_notes.append("For mirrors, the mirror surface/frame is legal; a shelf, stand, wall panel, or white base is illegal.")
        if any(word in text for word in ("cabinet", "dresser", "nightstand", "wardrobe", "chest", "table", "chair", "sofa", "bed")):
            object_notes.append("For furniture, visible legs/body/bedding are legal; a display plinth or white platform under it is illegal.")
        return {"legal": legal, "illegal": illegal, "object_notes": object_notes}

    @staticmethod
    def _requires_exposed_furniture_supports(object_text: str | None) -> bool:
        """Return whether the generation contract requires visible local supports.

        This is intentionally narrower than a generic furniture-name check.
        Closed boxes, cabinets, platform beds, lamp bases, and real plant pots
        may legitimately have continuous lower bodies.  A sofa/chair prompt
        that explicitly asks for visible or separated legs may not use that
        ambiguity to excuse a broad connected staging slab.
        """

        text = " ".join(str(object_text or "").lower().replace("_", " ").split())
        exposed_terms = (
            "visible legs",
            "separated legs",
            "stable support legs",
            "stable separated legs",
            "furniture legs",
        )
        seating_terms = (
            "sofa",
            "chair",
            "accent chair",
            "dining chair",
            "office chair",
            "lounge chair",
            "armchair",
            "stool",
            "ottoman",
        )
        explicit_continuous_support = any(
            term in text
            for term in (
                "pedestal chair",
                "pedestal stool",
                "solid plinth",
                "platform sofa",
                "continuous designed base",
            )
        )
        articulated_wheeled_support = (
            "office chair" in text
            and any(term in text for term in ("wheel", "wheeled", "caster"))
        )
        return any(term in text for term in exposed_terms) or (
            any(term in text for term in seating_terms)
            and not explicit_continuous_support
            and not articulated_wheeled_support
        )

    def _white_like_mask(self, rgba: np.ndarray) -> np.ndarray:
        rgb = rgba[:, :, :3].astype(np.uint8)
        try:
            import cv2

            hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
            saturation = hsv[:, :, 1].astype(np.float32)
            value = hsv[:, :, 2].astype(np.float32)
            return (saturation <= float(getattr(self.args, "white_base_saturation_threshold", 72.0))) & (
                value >= float(getattr(self.args, "white_base_value_threshold", 170.0))
            )
        except Exception:
            rgb_float = rgb.astype(np.float32)
            maxc = rgb_float.max(axis=2)
            minc = rgb_float.min(axis=2)
            saturation = np.zeros_like(maxc)
            np.divide(maxc - minc, np.maximum(maxc, 1e-6), out=saturation, where=maxc > 1e-6)
            saturation *= 255.0
            return (saturation <= float(getattr(self.args, "white_base_saturation_threshold", 72.0))) & (
                maxc >= float(getattr(self.args, "white_base_value_threshold", 170.0))
            )

    def _component_stats_for_mask(self, mask: np.ndarray) -> list[dict[str, Any]]:
        try:
            import cv2

            num, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
            components: list[dict[str, Any]] = []
            for label in range(1, num):
                x = int(stats[label, cv2.CC_STAT_LEFT])
                y = int(stats[label, cv2.CC_STAT_TOP])
                w = int(stats[label, cv2.CC_STAT_WIDTH])
                h = int(stats[label, cv2.CC_STAT_HEIGHT])
                area = int(stats[label, cv2.CC_STAT_AREA])
                components.append({"bbox": [x, y, x + w, y + h], "area": area})
            return components
        except Exception:
            # Keep this path dependency-free. A single global bbox is too coarse here because
            # legal white object parts, such as a mirror face, may otherwise merge with an
            # illegal white display base in the QA report.
            binary = mask.astype(bool)
            visited = np.zeros(binary.shape, dtype=bool)
            height, width = binary.shape
            components: list[dict[str, Any]] = []
            ys, xs = np.nonzero(binary)
            for start_y, start_x in zip(ys.tolist(), xs.tolist()):
                if visited[start_y, start_x] or not binary[start_y, start_x]:
                    continue
                stack = [(int(start_y), int(start_x))]
                visited[start_y, start_x] = True
                min_x = max_x = int(start_x)
                min_y = max_y = int(start_y)
                area = 0
                while stack:
                    y, x = stack.pop()
                    area += 1
                    min_x = min(min_x, x)
                    max_x = max(max_x, x)
                    min_y = min(min_y, y)
                    max_y = max(max_y, y)
                    for ny in range(max(0, y - 1), min(height, y + 2)):
                        for nx in range(max(0, x - 1), min(width, x + 2)):
                            if visited[ny, nx] or not binary[ny, nx]:
                                continue
                            visited[ny, nx] = True
                            stack.append((ny, nx))
                components.append(
                    {"bbox": [min_x, min_y, max_x + 1, max_y + 1], "area": int(area)}
                )
            return components

    def _white_base_topology_report(
        self,
        foreground: np.ndarray,
        *,
        candidate_bbox: list[int],
        foreground_bbox: list[int],
    ) -> dict[str, Any]:
        """Check whether a low white region is geometrically separate from the body.

        Colour alone is unsafe: a cream box body or pale book pages can satisfy the
        old white-platform heuristic. A removable base must instead be detached or
        meet the subject through a substantially narrower support immediately above
        its top edge.
        """

        x0, y0, x1, _ = candidate_bbox
        fg_x0, fg_y0, fg_x1, fg_y1 = foreground_bbox
        fg_h = max(1, fg_y1 - fg_y0)
        candidate_width = max(1, x1 - x0)
        band_height_ratio = float(
            getattr(self.args, "white_base_support_band_height_ratio", 0.04)
        )
        band_height = max(2, int(round(fg_h * band_height_ratio)))
        band_y0 = max(fg_y0, y0 - band_height)
        support_band = foreground[band_y0:y0, x0:x1]
        if support_band.size:
            row_occupancies = np.count_nonzero(support_band, axis=1) / float(
                candidate_width
            )
            maximum_support_occupancy = float(np.max(row_occupancies))
            mean_support_occupancy = float(np.mean(row_occupancies))
        else:
            maximum_support_occupancy = 0.0
            mean_support_occupancy = 0.0
        maximum_allowed = float(
            getattr(self.args, "white_base_max_support_occupancy_ratio", 0.55)
        )
        separated_or_narrowly_supported = maximum_support_occupancy <= maximum_allowed
        return {
            "support_band_bbox": [x0, band_y0, x1, y0],
            "support_band_height_ratio": band_height_ratio,
            "maximum_support_occupancy_ratio": round(maximum_support_occupancy, 6),
            "mean_support_occupancy_ratio": round(mean_support_occupancy, 6),
            "maximum_allowed_support_occupancy_ratio": maximum_allowed,
            "detached_from_subject": not bool(np.any(support_band)),
            "separated_or_narrowly_supported": separated_or_narrowly_supported,
            "foreground_bbox": [fg_x0, fg_y0, fg_x1, fg_y1],
        }

    def _white_base_repair_damage_report(
        self,
        before: np.ndarray,
        after: np.ndarray,
        *,
        protected_upper_y: int,
    ) -> dict[str, Any]:
        """Reject repairs that erase too much foreground or cut through a subject."""

        threshold = int(getattr(self.args, "alpha_bbox_threshold", 24))
        before_fg = before[:, :, 3] > threshold
        after_fg = after[:, :, 3] > threshold
        removed = before_fg & ~after_fg
        before_count = int(np.count_nonzero(before_fg))
        removed_count = int(np.count_nonzero(removed))
        removed_fraction = removed_count / float(max(1, before_count))
        upper_before = before_fg[:protected_upper_y]
        upper_removed = removed[:protected_upper_y]
        upper_removed_fraction = int(np.count_nonzero(upper_removed)) / float(
            max(1, int(np.count_nonzero(upper_before)))
        )

        ys, xs = np.nonzero(before_fg)
        horizontal_sever = False
        severed_rows: list[int] = []
        if len(xs) and len(ys):
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            width = max(1, x1 - x0)
            before_rows = np.count_nonzero(before_fg[y0:y1, x0:x1], axis=1)
            after_rows = np.count_nonzero(after_fg[y0:y1, x0:x1], axis=1)
            surviving = after_rows > 0
            for local_y, (old_count, new_count) in enumerate(
                zip(before_rows.tolist(), after_rows.tolist())
            ):
                if old_count < width * 0.45 or new_count > old_count * 0.25:
                    continue
                if np.any(surviving[:local_y]) and np.any(surviving[local_y + 1 :]):
                    horizontal_sever = True
                    severed_rows.append(y0 + local_y)
                    if len(severed_rows) >= 8:
                        break

        max_removed_fraction = float(
            getattr(
                self.args,
                "white_base_repair_max_removed_foreground_fraction",
                0.35,
            )
        )
        max_upper_removed_fraction = float(
            getattr(
                self.args,
                "white_base_repair_max_upper_removed_fraction",
                0.005,
            )
        )
        reasons: list[str] = []
        if removed_fraction > max_removed_fraction:
            reasons.append("removed_foreground_fraction_too_large")
        if upper_removed_fraction > max_upper_removed_fraction:
            reasons.append("removed_protected_upper_body")
        if horizontal_sever:
            reasons.append("introduced_horizontal_subject_cut")
        return {
            "ok": not reasons,
            "reasons": reasons,
            "removed_foreground_pixels": removed_count,
            "original_foreground_pixels": before_count,
            "removed_foreground_fraction": round(removed_fraction, 6),
            "maximum_removed_foreground_fraction": max_removed_fraction,
            "protected_upper_y": int(protected_upper_y),
            "removed_protected_upper_fraction": round(upper_removed_fraction, 6),
            "maximum_removed_protected_upper_fraction": max_upper_removed_fraction,
            "introduced_horizontal_subject_cut": horizontal_sever,
            "severed_rows": severed_rows,
        }
    def _white_base_artifact_report(self, rgba: np.ndarray, object_text: str | None = None) -> dict[str, Any]:
        enabled = bool(getattr(self.args, "white_base_quality_check", True))
        policy_notes = self._white_base_policy_notes(object_text)
        limits = {
            "bottom_start_ratio": float(getattr(self.args, "white_base_bottom_start_ratio", 0.58)),
            "top_slack_ratio": float(getattr(self.args, "white_base_top_slack_ratio", 0.035)),
            "min_width_ratio": float(getattr(self.args, "white_base_min_width_ratio", 0.50)),
            "max_height_ratio": float(getattr(self.args, "white_base_max_height_ratio", 0.45)),
            "bedlike_max_height_ratio": float(getattr(self.args, "white_base_bedlike_max_height_ratio", 0.20)),
            "min_aspect_ratio": float(getattr(self.args, "white_base_min_aspect_ratio", 1.55)),
            "min_area_ratio": float(getattr(self.args, "white_base_min_area_ratio", 0.010)),
            "white_saturation_threshold": float(getattr(self.args, "white_base_saturation_threshold", 72.0)),
            "white_value_threshold": float(getattr(self.args, "white_base_value_threshold", 170.0)),
            "connected_min_width_ratio": float(getattr(self.args, "connected_base_min_width_ratio", 0.72)),
            "connected_max_height_ratio": float(getattr(self.args, "connected_base_max_height_ratio", 0.24)),
            "connected_min_aspect_ratio": float(getattr(self.args, "connected_base_min_aspect_ratio", 6.0)),
            "connected_min_bottom_ratio": float(getattr(self.args, "connected_base_min_bottom_ratio", 0.72)),
        }
        report: dict[str, Any] = {
            "enabled": enabled,
            "ok": True,
            "reasons": [],
            "policy_notes": policy_notes,
            "limits": limits,
            "candidates": [],
        }
        if not enabled:
            return report

        alpha = rgba[:, :, 3]
        foreground = alpha > int(getattr(self.args, "alpha_bbox_threshold", 24))
        ys, xs = np.nonzero(foreground)
        if len(xs) == 0 or len(ys) == 0:
            report["reasons"].append("no_foreground")
            return report

        context = str(object_text or "").lower()
        bedlike_context = any(word in context for word in ("bed", "mattress", "duvet", "bedding", "pillow", "cushion", "blanket"))
        max_height_ratio = limits["bedlike_max_height_ratio"] if bedlike_context else limits["max_height_ratio"]
        report["context"] = {
            "object_text": object_text,
            "bedlike_white_material_allowed": bedlike_context,
            "active_max_height_ratio": max_height_ratio,
            "exposed_furniture_supports_required": (
                self._requires_exposed_furniture_supports(object_text)
            ),
        }

        fg_x0, fg_x1 = int(xs.min()), int(xs.max()) + 1
        fg_y0, fg_y1 = int(ys.min()), int(ys.max()) + 1
        fg_w = max(1, fg_x1 - fg_x0)
        fg_h = max(1, fg_y1 - fg_y0)
        fg_area = max(1, int(np.count_nonzero(foreground)))
        bottom_start = fg_y0 + int(round(fg_h * limits["bottom_start_ratio"]))
        white_like = self._white_like_mask(rgba)
        candidate_mask = foreground & white_like
        candidate_mask[:bottom_start, :] = False

        components = self._component_stats_for_mask(candidate_mask)
        violating: list[dict[str, Any]] = []
        for component in components:
            x0, y0, x1, y1 = [int(v) for v in component["bbox"]]
            area = int(component["area"])
            comp_w = max(1, x1 - x0)
            comp_h = max(1, y1 - y0)
            width_ratio = comp_w / float(fg_w)
            height_ratio = comp_h / float(fg_h)
            area_ratio = area / float(fg_area)
            aspect_ratio = comp_w / float(comp_h)
            bottom_ratio = (y1 - fg_y0) / float(fg_h)
            top_ratio = (y0 - fg_y0) / float(fg_h)
            center_x_ratio = ((x0 + x1) * 0.5 - fg_x0) / float(fg_w)
            stats = {
                "bbox": [x0, y0, x1, y1],
                "area": area,
                "width_ratio": round(width_ratio, 4),
                "height_ratio": round(height_ratio, 4),
                "area_ratio": round(area_ratio, 4),
                "aspect_ratio": round(aspect_ratio, 4),
                "top_ratio": round(top_ratio, 4),
                "bottom_ratio": round(bottom_ratio, 4),
                "center_x_ratio": round(center_x_ratio, 4),
            }
            color_geometry_candidate = (
                width_ratio >= limits["min_width_ratio"]
                and height_ratio <= max_height_ratio
                and aspect_ratio >= limits["min_aspect_ratio"]
                and area_ratio >= limits["min_area_ratio"]
                and bottom_ratio >= 0.86
                and top_ratio >= limits["bottom_start_ratio"] - limits["top_slack_ratio"]
            )
            connected_furniture_candidate = bool(
                report["context"]["exposed_furniture_supports_required"]
                and width_ratio >= limits["connected_min_width_ratio"]
                and height_ratio <= limits["connected_max_height_ratio"]
                and aspect_ratio >= limits["connected_min_aspect_ratio"]
                and area_ratio >= limits["min_area_ratio"]
                and bottom_ratio >= limits["connected_min_bottom_ratio"]
                and top_ratio
                >= limits["bottom_start_ratio"] - limits["top_slack_ratio"]
            )
            topology = self._white_base_topology_report(
                foreground,
                candidate_bbox=[x0, y0, x1, y1],
                foreground_bbox=[fg_x0, fg_y0, fg_x1, fg_y1],
            )
            stats["topology"] = topology
            disconnected_base = color_geometry_candidate and bool(
                topology["separated_or_narrowly_supported"]
            )
            connected_base = connected_furniture_candidate and not bool(
                topology["separated_or_narrowly_supported"]
            )
            is_low_wide_base = bool(disconnected_base or connected_base)
            stats["connected_furniture_contract_candidate"] = (
                connected_furniture_candidate
            )
            if connected_base:
                stats["decision"] = "illegal_connected_base_candidate"
            elif disconnected_base:
                stats["decision"] = "illegal_base_candidate"
            elif color_geometry_candidate:
                stats["decision"] = "protected_connected_subject_region"
            else:
                stats["decision"] = "ignored_legal_or_non_base_white_region"
            report["candidates"].append(stats)
            if is_low_wide_base:
                violating.append(stats)

        if violating:
            report["ok"] = False
            report["reasons"].append("illegal_white_base_or_platform")
            report["violating_candidates"] = violating
        return report

    def _repair_white_base_artifacts(
        self,
        rgba: np.ndarray,
        quality: dict[str, Any],
        object_text: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        enabled = bool(getattr(self.args, "white_base_auto_repair", True))
        report: dict[str, Any] = {
            "enabled": enabled,
            "applied": False,
            "object_text": object_text,
            "repairs": [],
        }
        if not enabled:
            return rgba, report

        white_report = quality.get("white_base_artifact", {}) if isinstance(quality, dict) else {}
        violating = white_report.get("violating_candidates", []) if isinstance(white_report, dict) else []
        if not violating:
            return rgba, report

        original = rgba.copy()
        repaired = rgba.copy()
        alpha = repaired[:, :, 3]
        foreground = alpha > int(getattr(self.args, "alpha_bbox_threshold", 24))
        ys, xs = np.nonzero(foreground)
        if len(xs) == 0 or len(ys) == 0:
            return repaired, report

        fg_x0, fg_x1 = int(xs.min()), int(xs.max()) + 1
        fg_y0, fg_y1 = int(ys.min()), int(ys.max()) + 1
        fg_w = max(1, fg_x1 - fg_x0)
        fg_h = max(1, fg_y1 - fg_y0)
        text = str(object_text or "").lower()
        plantlike_context = any(word in text for word in ("plant", "potted", "pot", "vase"))
        white_like = self._white_like_mask(repaired)
        repair_min_row_width_ratio = float(getattr(self.args, "white_base_repair_min_row_width_ratio", 0.22))
        if plantlike_context:
            repair_min_row_width_ratio = max(
                repair_min_row_width_ratio,
                float(getattr(self.args, "white_base_repair_plant_min_row_width_ratio", 0.38)),
            )
        min_row_width = max(3, int(round(fg_w * repair_min_row_width_ratio)))
        repair_start_ratio = float(getattr(self.args, "white_base_repair_start_ratio", 0.64))
        plant_center_keep_width_ratio = float(getattr(self.args, "white_base_repair_plant_center_keep_width_ratio", 0.56))
        min_remove_pixels = max(8, int(round(fg_w * fg_h * float(getattr(self.args, "white_base_repair_min_area_ratio", 0.001)))))
        fg_center_x = (fg_x0 + fg_x1) * 0.5
        plant_keep_half_width = fg_w * plant_center_keep_width_ratio * 0.5
        protected_upper_y = repaired.shape[0]

        for candidate in violating:
            bbox = candidate.get("bbox") if isinstance(candidate, dict) else None
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            x0, y0, x1, y1 = [int(v) for v in bbox]
            x0 = max(0, x0)
            y0 = max(0, y0)
            x1 = min(repaired.shape[1], x1)
            y1 = min(repaired.shape[0], y1)
            if x1 <= x0 or y1 <= y0:
                continue
            topology = candidate.get("topology", {}) if isinstance(candidate, dict) else {}
            if not bool(topology.get("separated_or_narrowly_supported", False)):
                continue
            protected_upper_y = min(protected_upper_y, y0)

            local = white_like[y0:y1, x0:x1] & (alpha[y0:y1, x0:x1] > int(getattr(self.args, "alpha_bbox_threshold", 24)))
            remove_local = np.zeros_like(local, dtype=bool)
            absolute_repair_start = fg_y0 + int(round(fg_h * repair_start_ratio))
            for local_y in range(local.shape[0]):
                global_y = y0 + local_y
                if global_y < absolute_repair_start:
                    continue
                cols = np.nonzero(local[local_y])[0]
                if len(cols) == 0:
                    continue
                row_span = int(cols.max() - cols.min() + 1)
                if row_span >= min_row_width:
                    candidate_top_ratio = float(candidate.get("top_ratio", 0.0)) if isinstance(candidate, dict) else 0.0
                    protect_plant_center = plantlike_context and candidate_top_ratio < 0.86
                    if protect_plant_center:
                        global_xs = x0 + np.arange(cols.min(), cols.max() + 1)
                        outside_pot_core = np.abs(global_xs.astype(np.float32) - float(fg_center_x)) > plant_keep_half_width
                        row_values = local[local_y, cols.min() : cols.max() + 1]
                        remove_local[local_y, cols.min() : cols.max() + 1] = row_values & outside_pot_core
                    else:
                        remove_local[local_y, cols.min() : cols.max() + 1] = local[local_y, cols.min() : cols.max() + 1]

            removed_pixels = int(np.count_nonzero(remove_local))
            if removed_pixels < min_remove_pixels:
                continue
            alpha_crop = alpha[y0:y1, x0:x1]
            alpha_crop[remove_local] = 0
            alpha[y0:y1, x0:x1] = alpha_crop
            report["repairs"].append(
                {
                    "candidate_bbox": [x0, y0, x1, y1],
                    "removed_pixels": removed_pixels,
                    "min_row_width": min_row_width,
                    "repair_start_ratio": repair_start_ratio,
                    "method": "clear_low_wide_white_rows_only",
                    "plantlike_center_preserved": plantlike_context and float(candidate.get("top_ratio", 0.0)) < 0.86,
                    "note": "Only near-white pixels in low, horizontally wide rows are removed; legal white pots/shades/bedding above the base are preserved.",
                }
            )

        repaired[:, :, 3] = alpha
        report["attempted"] = bool(report["repairs"])
        report["attempted_repair_count"] = len(report["repairs"])
        if not report["repairs"]:
            report["repair_count"] = 0
            return original, report
        damage = self._white_base_repair_damage_report(
            original,
            repaired,
            protected_upper_y=protected_upper_y,
        )
        report["damage_audit"] = damage
        if not damage["ok"]:
            report["applied"] = False
            report["repair_count"] = 0
            report["rolled_back"] = True
            report["rollback_reason"] = "damage_audit_failed"
            return original, report
        report["applied"] = True
        report["repair_count"] = len(report["repairs"])
        report["rolled_back"] = False
        return repaired, report

    def _alpha_quality_report(self, rgba: np.ndarray, object_text: str | None = None) -> dict[str, Any]:
        alpha = rgba[:, :, 3]
        threshold = int(self.args.alpha_bbox_threshold)
        foreground = alpha > threshold
        total = float(alpha.size)
        foreground_ratio = float(np.count_nonzero(foreground)) / total
        border = np.concatenate([foreground[0, :], foreground[-1, :], foreground[:, 0], foreground[:, -1]])
        border_foreground_ratio = float(np.count_nonzero(border)) / float(border.size)
        ys, xs = np.nonzero(foreground)
        bbox_area_ratio = 0.0
        bbox_fill_ratio = 0.0
        bbox: list[int] | None = None
        if len(xs) and len(ys):
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            bbox_area = float(max(1, (x1 - x0) * (y1 - y0)))
            bbox_area_ratio = bbox_area / total
            bbox_fill_ratio = float(np.count_nonzero(foreground)) / bbox_area
            bbox = [x0, y0, x1, y1]

        reasons: list[str] = []
        if foreground_ratio < float(self.args.alpha_min_foreground_ratio):
            reasons.append("foreground_too_small")
        if foreground_ratio > float(self.args.alpha_max_foreground_ratio):
            reasons.append("foreground_too_large")
        if border_foreground_ratio > float(self.args.alpha_max_border_foreground_ratio):
            reasons.append("foreground_touches_border")
        if bbox_area_ratio > 0.92 and bbox_fill_ratio > 0.82:
            reasons.append("large_filled_rectangle")
        white_base_artifact = self._white_base_artifact_report(rgba, object_text)
        if not bool(white_base_artifact.get("ok", True)):
            reasons.extend(str(reason) for reason in white_base_artifact.get("reasons", []))
        exposed_support_background_gap = self._exposed_support_background_gap_report(
            rgba, object_text
        )
        if not bool(exposed_support_background_gap.get("ok", True)):
            reasons.extend(
                str(reason)
                for reason in exposed_support_background_gap.get("reasons", [])
            )

        score = 1.0
        score -= max(0.0, float(self.args.alpha_min_foreground_ratio) - foreground_ratio) * 8.0
        score -= max(0.0, foreground_ratio - float(self.args.alpha_max_foreground_ratio)) * 4.0
        score -= max(0.0, border_foreground_ratio - float(self.args.alpha_max_border_foreground_ratio)) * 6.0
        if "large_filled_rectangle" in reasons:
            score -= 0.35
        if "illegal_white_base_or_platform" in reasons:
            score -= float(getattr(self.args, "white_base_score_penalty", 0.65))
        if "exposed_support_background_gap_missing" in reasons:
            score -= float(getattr(self.args, "support_gap_score_penalty", 0.65))

        return {
            "ok": not reasons,
            "reasons": reasons,
            "score": round(max(-1.0, score), 4),
            "foreground_ratio": round(foreground_ratio, 6),
            "border_foreground_ratio": round(border_foreground_ratio, 6),
            "bbox": bbox,
            "bbox_area_ratio": round(bbox_area_ratio, 6),
            "bbox_fill_ratio": round(bbox_fill_ratio, 6),
            "white_base_artifact": white_base_artifact,
            "exposed_support_background_gap": exposed_support_background_gap,
            "threshold": threshold,
            "limits": {
                "min_foreground_ratio": float(self.args.alpha_min_foreground_ratio),
                "max_foreground_ratio": float(self.args.alpha_max_foreground_ratio),
                "max_border_foreground_ratio": float(self.args.alpha_max_border_foreground_ratio),
            },
        }

    def _alpha_metadata_path(self, job_id: str) -> Path:
        return Path(self.args.output_dir) / "reference_rgba" / f"{job_id}.alpha.json"

    def _read_alpha_metadata(self, job_id: str) -> dict[str, Any]:
        path = self._alpha_metadata_path(job_id)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _alpha_metadata_ok(self, metadata: dict[str, Any]) -> bool:
        normalization = metadata.get("native_alpha_normalization")
        if isinstance(normalization, dict) and not opacity_review_ok(normalization):
            return False
        if not self.args.alpha_quality_check:
            return True
        quality = metadata.get("alpha_quality")
        if not isinstance(quality, dict):
            return True
        return bool(quality.get("ok", True))

    def _attempt_has_white_base_violation(self, attempt: dict[str, Any]) -> bool:
        quality = attempt.get("alpha_metadata", {}).get("alpha_quality", {})
        if not isinstance(quality, dict):
            return False
        reasons = quality.get("reasons", [])
        if isinstance(reasons, list) and "illegal_white_base_or_platform" in reasons:
            return True
        white_report = quality.get("white_base_artifact", {})
        return isinstance(white_report, dict) and not bool(white_report.get("ok", True))

    @staticmethod
    def _attempt_has_background_isolation_violation(
        attempt: dict[str, Any],
    ) -> bool:
        metadata = attempt.get("alpha_metadata")
        if not isinstance(metadata, dict):
            return True
        normalization = metadata.get("native_alpha_normalization")
        if isinstance(normalization, dict) and not opacity_review_ok(normalization):
            return True
        source_white = metadata.get("source_white_background")
        if not isinstance(source_white, dict):
            return True
        if bool(source_white.get("enforced")) and not bool(source_white.get("ok")):
            return True
        isolation = metadata.get("white_background_isolation")
        if not isinstance(isolation, dict) or not bool(isolation.get("ok")):
            return True
        quality = metadata.get("alpha_quality")
        quality = quality if isinstance(quality, dict) else {}
        support_gap = quality.get("exposed_support_background_gap")
        return bool(
            isinstance(support_gap, dict)
            and support_gap.get("required")
            and not support_gap.get("ok")
        )

    def _save_prepared_rgba(
        self,
        rgba: np.ndarray,
        image_path: Path,
        job_id: str,
        method: str,
        object_text: str | None = None,
        enforce_white_background: bool = False,
        extra: dict[str, Any] | None = None,
        source_white_rgba: np.ndarray | None = None,
    ) -> Path:
        source_white_background = self._source_white_background_report(
            rgba if source_white_rgba is None else source_white_rgba,
            enforced=enforce_white_background,
        )
        normalization = (extra or {}).get("native_alpha_normalization")
        if isinstance(normalization, dict):
            visible_record = normalization["records"]["source_visible_white_rgb"]
            source_white_background.update(
                input_semantics="native_alpha_visible_white",
                source_image_path=visible_record["path"],
                source_image_sha256=visible_record["sha256"],
                alpha_max=int(getattr(self.args, "white_background_alpha_max", 8)),
            )
        rgba, source_chroma_cleanup = clean_chromatic_alpha_edges(
            rgba,
            foreground_alpha_threshold=int(self.args.alpha_bbox_threshold),
            maximum_visible_spill_fraction=float(
                getattr(self.args, "alpha_max_visible_chroma_spill_fraction", 0.12)
            ),
            maximum_alpha_weight_removed_fraction=float(
                getattr(self.args, "alpha_max_chroma_cleanup_removed_fraction", 0.12)
            ),
        )
        # Preserve QA in the original RMBG coordinate frame as evidence for
        # the raw Flux image.  Recentring is useful for TRELLIS, but must not
        # erase the fact that a suspicious support surface was present before
        # that transform.
        source_frame_alpha_quality = self._alpha_quality_report(
            rgba, object_text
        )
        rgba = self._center_foreground_on_transparent_canvas(rgba)
        white_base_repair: dict[str, Any] = {
            "enabled": bool(getattr(self.args, "white_base_auto_repair", True)),
            "applied": False,
            "passes": [],
        }
        max_repair_passes = max(1, int(getattr(self.args, "white_base_repair_max_passes", 3)))
        for repair_pass in range(max_repair_passes):
            current_quality = self._alpha_quality_report(rgba, object_text)
            if bool(current_quality.get("ok", True)) or "illegal_white_base_or_platform" not in current_quality.get("reasons", []):
                white_base_repair["stop_reason"] = "quality_passed" if repair_pass else "no_initial_white_base_violation"
                break
            repaired_rgba, pass_report = self._repair_white_base_artifacts(rgba, current_quality, object_text)
            pass_report["pass_index"] = repair_pass
            white_base_repair["passes"].append(pass_report)
            if not pass_report.get("applied"):
                white_base_repair["stop_reason"] = "repair_not_applicable"
                break
            rgba = repaired_rgba
            if pass_report.get("applied"):
                rgba = self._center_foreground_on_transparent_canvas(rgba)
        else:
            white_base_repair["stop_reason"] = "max_repair_passes_reached"
        white_base_repair["applied"] = any(bool(item.get("applied")) for item in white_base_repair.get("passes", []))
        white_base_repair["repair_count"] = sum(int(item.get("repair_count", 0) or 0) for item in white_base_repair.get("passes", []))
        white_base_repair["attempted_repair_count"] = sum(
            int(item.get("attempted_repair_count", 0) or 0)
            for item in white_base_repair.get("passes", [])
        )
        white_base_repair["rolled_back"] = any(
            bool(item.get("rolled_back"))
            for item in white_base_repair.get("passes", [])
        )
        # Repairs and Lanczos recentering happen after the source matte is
        # cleaned, so verify the final pixels against the *recorded* source
        # background instead of trying to infer a new background from subject
        # antialiasing. Fully transparent RGB is normalized one final time.
        final_hidden_rgb_zeroed = int(
            np.count_nonzero(
                (rgba[:, :, 3] == 0)
                & np.any(rgba[:, :, :3] != 0, axis=2)
            )
        )
        rgba[:, :, :3][rgba[:, :, 3] == 0] = 0
        hidden_rgb_nonzero_after_normalization = int(
            np.count_nonzero(
                (rgba[:, :, 3] == 0)
                & np.any(rgba[:, :, :3] != 0, axis=2)
            )
        )
        background_estimate = source_chroma_cleanup.get("background_estimate", {})
        background_rgb = (
            background_estimate.get("background_rgb")
            if isinstance(background_estimate, dict)
            and background_estimate.get("evaluated")
            else None
        )
        prepared_chroma_audit = audit_sanitized_alpha_edges(
            rgba,
            background_rgb,
            foreground_alpha_threshold=int(self.args.alpha_bbox_threshold),
            maximum_visible_spill_fraction=float(
                getattr(self.args, "alpha_max_visible_chroma_spill_fraction", 0.12)
            ),
        )
        chroma_reasons = list(source_chroma_cleanup.get("reasons", [])) + list(
            prepared_chroma_audit.get("reasons", [])
        )
        chroma_hygiene = {
            "schema": "scene_dna_alpha_chroma_hygiene_provenance_v2",
            "ok": bool(source_chroma_cleanup.get("ok", True))
            and bool(prepared_chroma_audit.get("ok", True)),
            "background_rgb": background_rgb,
            "source_cleanup": source_chroma_cleanup,
            "prepared_audit": prepared_chroma_audit,
            "final_hidden_rgb_zeroed_pixel_count": final_hidden_rgb_zeroed,
            "reasons": list(dict.fromkeys(chroma_reasons)),
        }
        alpha = rgba[:, :, 3]
        prepared = Path(self.args.output_dir) / "reference_rgba" / f"{job_id}.png"
        prepared.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgba, mode="RGBA").save(prepared)
        mask_path = Path(self.args.output_dir) / "reference_masks" / f"{job_id}.png"
        mask_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(alpha, mode="L").save(mask_path)
        foreground = float(np.count_nonzero(alpha > 16)) / float(alpha.size)
        quality = self._alpha_quality_report(rgba, object_text)
        if isinstance(normalization, dict) and not opacity_review_ok(normalization):
            quality["ok"] = False
            quality["reasons"] = list(quality.get("reasons", [])) + ["native_alpha_opacity_review_required"]
        if not bool(source_white_background.get("ok", True)):
            quality["ok"] = False
            quality["reasons"] = list(
                dict.fromkeys(
                    list(quality.get("reasons", []))
                    + list(source_white_background.get("reasons", []))
                )
            )
            quality["score"] = round(
                max(-1.0, float(quality.get("score", 0.0)) - 0.65), 4
            )
        quality["chroma_spill_hygiene"] = chroma_hygiene
        if not bool(chroma_hygiene.get("ok", True)):
            quality["ok"] = False
            quality["reasons"] = list(quality.get("reasons", [])) + list(
                chroma_hygiene.get("reasons", [])
            )
            quality["score"] = round(
                max(-1.0, float(quality.get("score", 0.0)) - 0.65), 4
            )
        normalized_white = (
            Path(self.args.output_dir) / "reference_white_rgb" / f"{job_id}.png"
        )
        normalized_white.parent.mkdir(parents=True, exist_ok=True)
        composite_on_review_background(
            rgba,
            background_rgb=(255, 255, 255),
        ).save(normalized_white)
        transparent = rgba[:, :, 3] == 0
        normalized_pixels = np.asarray(
            Image.open(normalized_white).convert("RGB"), dtype=np.uint8
        )
        exact_white_background = (
            bool(np.all(normalized_pixels[transparent] == 255))
            if np.any(transparent)
            else False
        )
        white_background_isolation = {
            "schema": "scene-v2-normalized-white-background-isolation/v1",
            "ok": bool(
                exact_white_background
                and hidden_rgb_nonzero_after_normalization == 0
                and quality.get("border_foreground_ratio", 1.0)
                <= float(self.args.alpha_max_border_foreground_ratio)
            ),
            "normalized_white_rgb_path": str(normalized_white),
            "exact_white_rgb": [255, 255, 255],
            "exact_white_for_all_alpha_zero_pixels": exact_white_background,
            "transparent_background_pixel_count": int(np.count_nonzero(transparent)),
            "hidden_rgb_zeroed": hidden_rgb_nonzero_after_normalization == 0,
            "hidden_rgb_normalized_pixel_count": final_hidden_rgb_zeroed,
            "foreground_touches_border": bool(
                quality.get("border_foreground_ratio", 1.0)
                > float(self.args.alpha_max_border_foreground_ratio)
            ),
            "trellis_input_uses_transparent_rgba": True,
        }
        if not white_background_isolation["ok"]:
            quality["ok"] = False
            quality["reasons"] = list(
                dict.fromkeys(
                    list(quality.get("reasons", []))
                    + ["white_background_isolation_failed"]
                )
            )
            quality["score"] = round(
                max(-1.0, float(quality.get("score", 0.0)) - 0.65), 4
            )
        metadata = {
            "source_image_path": str(image_path),
            "prepared_image_path": str(prepared),
            "normalized_white_image_path": str(normalized_white),
            "mask_path": str(mask_path),
            "foreground_ratio": foreground,
            "method": method,
            "object_text": object_text,
            "source_frame_alpha_quality": source_frame_alpha_quality,
            "source_white_background": source_white_background,
            "white_background_isolation": white_background_isolation,
            "alpha_quality": quality,
            "white_base_repair": white_base_repair,
        }
        if extra:
            metadata.update(extra)
        (Path(self.args.output_dir) / "reference_rgba" / f"{job_id}.alpha.json").write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )
        return prepared

    def _prepare_reference_with_rmbg(
        self,
        image_path: Path,
        job_id: str,
        pipeline: Any,
        object_text: str | None = None,
        enforce_white_background: bool = False,
    ) -> Path:
        if self.args.alpha_mode == "none":
            return image_path

        image = Image.open(image_path).convert("RGB")
        if self.args.alpha_mode != "rembg":
            raise RuntimeError("RMBG disabled by alpha mode")

        output = self._run_local_rmbg(image).convert("RGBA")

        rgba = np.array(output, dtype=np.uint8)
        alpha = rgba[:, :, 3]
        if not np.any(alpha < 255):
            raise RuntimeError("RMBG returned a fully opaque image")
        return self._save_prepared_rgba(
            rgba,
            image_path,
            job_id,
            method="rembg",
            object_text=object_text,
            enforce_white_background=enforce_white_background,
            extra={
                "rembg_model": self.args.rmbg_model,
                "trellis_rembg_args": getattr(pipeline, "_rembg_args", {}),
            },
        )

    def _rmbg_instance(self):
        if self._rembg_model is not None:
            return self._rembg_model, self._rembg_transform, self._rembg_to_pil, self._rembg_torch
        with self._rembg_lock:
            if self._rembg_model is not None:
                return self._rembg_model, self._rembg_transform, self._rembg_to_pil, self._rembg_torch

            module_root = Path(self.args.rmbg_module_root)
            if str(module_root) not in sys.path:
                sys.path.insert(0, str(module_root))
            from safetensors.torch import load_file
            import torch
            from torchvision import transforms

            model_dir = Path(self.args.rmbg_model)
            try:
                from transformers_modules.rmbg_2_0.BiRefNet_config import BiRefNetConfig
                from transformers_modules.rmbg_2_0.birefnet import BiRefNet
            except ModuleNotFoundError:
                model_parent = str(model_dir.parent)
                if model_parent not in sys.path:
                    sys.path.insert(0, model_parent)
                from rmbg_2_0.BiRefNet_config import BiRefNetConfig
                from rmbg_2_0.birefnet import BiRefNet

            print(f"[trellis2] loading RMBG model from {model_dir}", flush=True)
            model = BiRefNet(config=BiRefNetConfig(bb_pretrained=False))
            state = load_file(str(model_dir / "model.safetensors"), device="cpu")
            missing, unexpected = model.load_state_dict(state, strict=False)
            if missing or unexpected:
                print(
                    f"[trellis2] RMBG state dict loaded with missing={len(missing)} unexpected={len(unexpected)}",
                    flush=True,
                )
            model.eval()
            transform = transforms.Compose(
                [
                    transforms.Resize((1024, 1024)),
                    transforms.ToTensor(),
                    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
                ]
            )
            self._rembg_model = model
            self._rembg_transform = transform
            self._rembg_to_pil = transforms.ToPILImage()
            self._rembg_torch = torch
            return self._rembg_model, self._rembg_transform, self._rembg_to_pil, self._rembg_torch

    def _run_local_rmbg(self, image: Image.Image) -> Image.Image:
        model, transform, to_pil, torch = self._rmbg_instance()
        image_size = image.size
        with self._rembg_lock:
            model.to(self.args.device)
            input_images = transform(image).unsqueeze(0).to(self.args.device)
            with torch.no_grad():
                pred = model(input_images)[-1].sigmoid().detach().cpu()[0].squeeze()
            if self.args.rmbg_offload_cpu:
                model.cpu()
            mask = to_pil(pred).resize(image_size)
        output = image.convert("RGBA")
        output.putalpha(mask)
        return output

    def _prepare_reference_with_threshold(
        self,
        image_path: Path,
        job_id: str,
        object_text: str | None = None,
        enforce_white_background: bool = False,
    ) -> Path:
        native = self._prepare_native_alpha_reference(image_path, job_id, object_text, enforce_white_background)
        if native is not None:
            return native
        image = Image.open(image_path).convert("RGBA")
        rgba = np.array(image, dtype=np.uint8)
        existing_alpha = rgba[:, :, 3]
        if np.any(existing_alpha < 255):
            return self._save_prepared_rgba(
                rgba,
                image_path,
                job_id,
                method="existing_alpha",
                object_text=object_text,
                enforce_white_background=enforce_white_background,
            )

        rgb = rgba[:, :, :3].astype(np.float32)
        h, w = rgb.shape[:2]
        patch = max(8, min(h, w) // 10)
        corners = np.concatenate(
            [
                rgb[:patch, :patch].reshape(-1, 3),
                rgb[:patch, -patch:].reshape(-1, 3),
                rgb[-patch:, :patch].reshape(-1, 3),
                rgb[-patch:, -patch:].reshape(-1, 3),
            ],
            axis=0,
        )
        bg = np.median(corners, axis=0)
        dist = np.linalg.norm(rgb - bg[None, None, :], axis=2)
        try:
            import cv2

            hsv = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2HSV)
            saturation = hsv[:, :, 1].astype(np.float32)
            value = hsv[:, :, 2].astype(np.float32)
            white_like = (saturation <= float(self.args.bg_saturation_threshold)) & (
                value >= float(self.args.bg_value_threshold)
            )
            bg_like = (dist <= float(self.args.alpha_threshold)) | white_like

            # Only remove background regions connected to the image border. This avoids deleting
            # legitimate white parts inside an object while still removing white canvases/shadows.
            num_labels, labels = cv2.connectedComponents(bg_like.astype(np.uint8), connectivity=8)
            border_labels = np.unique(
                np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]])
            )
            bg_connected = np.isin(labels, border_labels)
            alpha_mask = ~bg_connected

            min_area = max(64, int(alpha_mask.size * float(self.args.alpha_min_component_ratio)))
            num_fg, fg_labels, stats, _ = cv2.connectedComponentsWithStats(alpha_mask.astype(np.uint8), connectivity=8)
            keep = np.zeros(num_fg, dtype=bool)
            for label in range(1, num_fg):
                keep[label] = stats[label, cv2.CC_STAT_AREA] >= min_area
            alpha_mask = keep[fg_labels]

            kernel_size = max(1, int(self.args.alpha_morph_kernel))
            if kernel_size > 1:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
                alpha_mask = cv2.morphologyEx(alpha_mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel).astype(bool)
            if int(self.args.alpha_dilate) > 0:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
                alpha_mask = cv2.dilate(alpha_mask.astype(np.uint8), kernel, iterations=int(self.args.alpha_dilate)).astype(bool)
            alpha = cv2.GaussianBlur((alpha_mask.astype(np.uint8) * 255), (5, 5), 0)
        except Exception as exc:
            print(f"[trellis2] alpha cutout fallback for {job_id}: {exc}", flush=True)
            alpha = np.where(dist > float(self.args.alpha_threshold), 255, 0).astype(np.uint8)

        rgba[:, :, 3] = alpha
        return self._save_prepared_rgba(
            rgba,
            image_path,
            job_id,
            method="threshold",
            object_text=object_text,
            enforce_white_background=enforce_white_background,
            extra={
                "background_rgb_median": [float(x) for x in bg],
                "alpha_threshold": float(self.args.alpha_threshold),
            },
        )

    def _prepare_native_alpha_reference(
        self, image_path: Path, job_id: str, object_text: str | None,
        enforce_white_background: bool, review: dict[str, Any] | None = None,
    ) -> Path | None:
        native = prepare_native_alpha_evidence(
            image_path, Path(self.args.output_dir), job_id, review=review,
        )
        if native is None:
            return None
        rgba, visible, normalization = native
        audit_rgba = rgba.copy()
        audit_rgba[:, :, :3] = visible
        return self._save_prepared_rgba(
            rgba, image_path, job_id, method="existing_alpha",
            object_text=object_text, enforce_white_background=enforce_white_background,
            source_white_rgba=audit_rgba,
            extra={
                "native_alpha_normalization": normalization,
                "source_white_input_path": normalization["records"]["source_visible_white_rgb"]["path"],
            },
        )

    def _prepare_reference_rgba(
        self,
        image_path: Path,
        job_id: str,
        pipeline: Any,
        object_text: str | None = None,
        enforce_white_background: bool = False,
        native_alpha_review: dict[str, Any] | None = None,
    ) -> Path:
        native = self._prepare_native_alpha_reference(
            image_path, job_id, object_text, enforce_white_background, native_alpha_review,
        )
        if native is not None:
            return native

        if self.args.alpha_mode == "threshold":
            return self._prepare_reference_with_threshold(
                image_path,
                job_id,
                object_text,
                enforce_white_background,
            )
        if self.args.alpha_mode == "none":
            return image_path
        try:
            prepared = self._prepare_reference_with_rmbg(
                image_path,
                job_id,
                pipeline,
                object_text,
                enforce_white_background,
            )
            metadata = self._read_alpha_metadata(job_id)
            if self._alpha_metadata_ok(metadata):
                return prepared
            if not self.args.alpha_fallback_threshold:
                return prepared
            quality = metadata.get("alpha_quality", {})
            print(
                f"[trellis2] RMBG alpha quality failed for {job_id}, using threshold fallback: "
                f"{quality.get('reasons', [])}",
                flush=True,
            )
            return self._prepare_reference_with_threshold(
                image_path,
                job_id,
                object_text,
                enforce_white_background,
            )
        except Exception as exc:
            if not self.args.alpha_fallback_threshold:
                raise
            print(f"[trellis2] RMBG failed for {job_id}, using threshold fallback: {exc}", flush=True)
            return self._prepare_reference_with_threshold(
                image_path,
                job_id,
                object_text,
                enforce_white_background,
            )

    def _mesh_count(self, value: Any) -> int | None:
        shape = getattr(value, "shape", None)
        if shape is not None and len(shape) > 0:
            try:
                return int(shape[0])
            except (TypeError, ValueError):
                return None
        try:
            return int(len(value))
        except TypeError:
            return None

    def _postprocess_to_glb_with_retries(
        self,
        o_voxel: Any,
        mesh: Any,
        payload: dict[str, Any],
    ) -> tuple[Any, list[dict[str, Any]]]:
        requested_decimation = int(payload.get("decimation_target", self.args.decimation_target))
        requested_texture_size = int(payload.get("texture_size", self.args.texture_size))
        requested_remesh = bool(payload.get("remesh", self.args.remesh))
        requested_remesh_band = int(payload.get("remesh_band", self.args.remesh_band))
        requested_remesh_project = int(payload.get("remesh_project", self.args.remesh_project))

        configs: list[dict[str, Any]] = [
            {
                "label": "requested",
                "decimation_target": requested_decimation,
                "texture_size": requested_texture_size,
                "remesh": requested_remesh,
                "remesh_band": requested_remesh_band,
                "remesh_project": requested_remesh_project,
                "pre_simplify_limit": None,
            }
        ]
        if requested_remesh:
            configs.append(
                {
                    "label": "no_remesh",
                    "decimation_target": requested_decimation,
                    "texture_size": requested_texture_size,
                    "remesh": False,
                    "remesh_band": requested_remesh_band,
                    "remesh_project": requested_remesh_project,
                    "pre_simplify_limit": None,
                }
            )
        for simplify_limit, decimation_target in ((262144, 200000), (131072, 100000)):
            configs.append(
                {
                    "label": f"pre_simplify_{simplify_limit}_no_remesh",
                    "decimation_target": min(requested_decimation, decimation_target),
                    "texture_size": min(requested_texture_size, 1024),
                    "remesh": False,
                    "remesh_band": requested_remesh_band,
                    "remesh_project": requested_remesh_project,
                    "pre_simplify_limit": simplify_limit,
                }
            )

        attempts: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for config in configs:
            attempt: dict[str, Any] = {
                **config,
                "mesh_vertices_before": self._mesh_count(getattr(mesh, "vertices", [])),
                "mesh_faces_before": self._mesh_count(getattr(mesh, "faces", [])),
            }
            start = time.time()
            try:
                if config["pre_simplify_limit"] is not None:
                    mesh.simplify(int(config["pre_simplify_limit"]))
                    attempt["mesh_vertices_after_pre_simplify"] = self._mesh_count(getattr(mesh, "vertices", []))
                    attempt["mesh_faces_after_pre_simplify"] = self._mesh_count(getattr(mesh, "faces", []))
                glb = o_voxel.postprocess.to_glb(
                    vertices=mesh.vertices,
                    faces=mesh.faces,
                    attr_volume=mesh.attrs,
                    coords=mesh.coords,
                    attr_layout=mesh.layout,
                    voxel_size=mesh.voxel_size,
                    aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
                    decimation_target=int(config["decimation_target"]),
                    texture_size=int(config["texture_size"]),
                    remesh=bool(config["remesh"]),
                    remesh_band=int(config["remesh_band"]),
                    remesh_project=int(config["remesh_project"]),
                    verbose=True,
                )
                attempt["ok"] = True
                attempt["elapsed_seconds"] = round(time.time() - start, 3)
                attempts.append(attempt)
                return glb, attempts
            except Exception as exc:  # pragma: no cover - depends on CUDA/CuMesh runtime behavior
                last_error = exc
                attempt["ok"] = False
                attempt["elapsed_seconds"] = round(time.time() - start, 3)
                attempt["error"] = f"{type(exc).__name__}: {exc}"
                attempt["traceback_tail"] = traceback.format_exc()[-4000:]
                attempts.append(attempt)
                torch_mod = self._torch
                if torch_mod is not None and hasattr(torch_mod, "cuda") and torch_mod.cuda.is_available():
                    torch_mod.cuda.empty_cache()
                print(
                    f"[trellis2] postprocess attempt failed ({config['label']}): {attempt['error']}",
                    flush=True,
                )

        raise RuntimeError(f"Trellis2 postprocess failed after {len(attempts)} attempts: {last_error}")

    def _is_cuda_oom(self, exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return "out of memory" in text and ("cuda" in text or "cumesh" in text)

    def _pipeline_fallback_types(self, requested_pipeline_type: str) -> list[str]:
        if requested_pipeline_type == "1536_cascade":
            return ["1536_cascade", "1024_cascade", "1024", "512"]
        if requested_pipeline_type == "1024_cascade":
            return ["1024_cascade", "1024", "512"]
        if requested_pipeline_type == "1024":
            return ["1024", "512"]
        return [requested_pipeline_type]

    def reprocess_native_alpha_candidate_cpu(self, payload: dict[str, Any], job_id: str) -> Path:
        """Replay a proven native-alpha raw artifact without model execution.

        This route runs the production existing-alpha preparation and evidence
        chain. An unreviewed opacity decision or failed QA remains a failure;
        the new attempt evidence is retained by ``generate`` before rejection.
        """
        if not payload.get("replay_reference_evidence") or payload.get("scene_dna"):
            raise ValueError("CPU native-alpha replay requires raw provenance and no SceneDNA scoring")
        candidate = next(iter(self._reference_candidates_for_payload(payload, job_id)))
        if decode_native_alpha(Path(candidate["source_image_path"])) is None:
            raise ValueError("CPU replay requires native transparency; RGB must use normal RMBG admission")
        return self.generate({**payload, "candidate_only": True}, job_id)

    def generate(self, payload: dict[str, Any], job_id: str) -> Path:
        output_dir = Path(self.args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_glb = output_dir / f"{job_id}.glb"
        metadata_path = output_dir / f"{job_id}.json"
        # Validate durable provenance storage before loading FLUX/TRELLIS or
        # accepting any candidate.  A job cannot succeed with evidence that
        # exists only in /tmp.
        persistent_job_evidence_root = self._persistent_evidence_root(job_id)

        reference_attempts: list[dict[str, Any]] = []
        selected_attempt: dict[str, Any] | None = None
        scene_dna_candidate_selection: dict[str, Any] | None = None
        last_error: str | None = None
        object_text = str(payload.get("input_text") or payload.get("prompt") or "").strip()
        collect_scene_dna_candidates = (
            self._scene_dna_payload(payload) is not None
            and self._scene_dna_candidate_count(payload) > 1
        )
        for candidate in self._reference_candidates_for_payload(payload, job_id):
            reference_job_id = str(candidate["reference_job_id"])
            source_image_path = Path(candidate["source_image_path"])
            try:
                image_path = self._prepare_reference_rgba(
                    source_image_path,
                    reference_job_id,
                    None,
                    object_text,
                    enforce_white_background=bool(candidate.get("generated") or candidate.get("enforce_white_background"))
                    and str(self.args.flux_background_mode) == "white",
                    native_alpha_review=payload.get("native_alpha_review"),
                )
                metadata = self._read_alpha_metadata(reference_job_id)
                attempt_report = {
                    **candidate,
                    "source_image_path": str(source_image_path),
                    "prepared_image_path": str(image_path),
                    "alpha_metadata": metadata,
                    "alpha_quality_ok": self._alpha_metadata_ok(metadata),
                }
                attempt_report = self._persist_reference_attempt_evidence(
                    job_id, attempt_report
                )
                reference_attempts.append(attempt_report)
                if attempt_report["alpha_quality_ok"]:
                    if not collect_scene_dna_candidates:
                        selected_attempt = attempt_report
                        break
                    continue
                quality = metadata.get("alpha_quality", {})
                print(
                    f"[trellis2] alpha quality failed for {reference_job_id}: "
                    f"{quality.get('reasons', [])}; trying next reference if available",
                    flush=True,
                )
            except Exception as exc:
                last_error = traceback.format_exc()
                reference_attempts.append(
                    {
                        **candidate,
                        "source_image_path": str(source_image_path),
                        "error": str(exc),
                    }
                )
                print(f"[trellis2] reference preparation failed for {reference_job_id}: {exc}", flush=True)

        if collect_scene_dna_candidates:
            selected_attempt, scene_dna_candidate_selection = (
                self._select_scene_dna_reference_attempt(reference_attempts, payload)
            )
        elif selected_attempt is None:
            usable_attempts = [a for a in reference_attempts if a.get("prepared_image_path")]
            if not usable_attempts:
                raise RuntimeError(last_error or "No usable reference image was prepared")
            usable_attempts = [
                a for a in usable_attempts
                if not isinstance(a.get("alpha_metadata", {}).get("native_alpha_normalization"), dict)
                or opacity_review_ok(a["alpha_metadata"]["native_alpha_normalization"])
            ]
            if not usable_attempts:
                raise RuntimeError("Native alpha opacity review required for all reference attempts")
            if bool(getattr(self.args, "white_base_require_clean", True)):
                clean_attempts = [a for a in usable_attempts if not self._attempt_has_white_base_violation(a)]
                if not clean_attempts:
                    reasons = [
                        {
                            "reference_job_id": a.get("reference_job_id"),
                            "reasons": a.get("alpha_metadata", {}).get("alpha_quality", {}).get("reasons", []),
                            "white_base_artifact": a.get("alpha_metadata", {}).get("alpha_quality", {}).get("white_base_artifact", {}),
                        }
                        for a in usable_attempts
                    ]
                    raise RuntimeError(f"All reference attempts failed white-base QA: {reasons}")
                usable_attempts = clean_attempts
            if bool(
                getattr(self.args, "background_isolation_require_clean", False)
            ):
                isolated_attempts = [
                    attempt
                    for attempt in usable_attempts
                    if not self._attempt_has_background_isolation_violation(attempt)
                ]
                if not isolated_attempts:
                    reasons = [
                        {
                            "reference_job_id": attempt.get("reference_job_id"),
                            "source_white_background": attempt.get(
                                "alpha_metadata", {}
                            ).get("source_white_background"),
                            "white_background_isolation": attempt.get(
                                "alpha_metadata", {}
                            ).get("white_background_isolation"),
                            "exposed_support_background_gap": attempt.get(
                                "alpha_metadata", {}
                            ).get("alpha_quality", {}).get(
                                "exposed_support_background_gap"
                            ),
                        }
                        for attempt in usable_attempts
                    ]
                    raise RuntimeError(
                        "All reference attempts failed white-background isolation QA: "
                        f"{reasons}"
                    )
                usable_attempts = isolated_attempts
            if self.args.alpha_require_quality:
                reasons = [
                    a.get("alpha_metadata", {}).get("alpha_quality", {}).get("reasons", [])
                    for a in usable_attempts
                ]
                raise RuntimeError(f"All alpha quality attempts failed: {reasons}")
            selected_attempt = max(
                usable_attempts,
                key=lambda a: float(a.get("alpha_metadata", {}).get("alpha_quality", {}).get("score", -1.0)),
            )
            print(
                f"[trellis2] using best failed alpha attempt for {job_id}: "
                f"{selected_attempt.get('reference_job_id')}",
                flush=True,
            )

        selected_normalization = selected_attempt.get("alpha_metadata", {}).get("native_alpha_normalization")
        if isinstance(selected_normalization, dict) and not opacity_review_ok(selected_normalization):
            raise RuntimeError("Native alpha opacity review required for selected reference")

        if bool(payload.get("candidate_only", False)):
            metadata_path.write_text(
                json.dumps(
                    {
                        "schema": "scene_dna_candidate_batch_result_v1",
                        "job_id": job_id,
                        "status": "candidate_batch_done",
                        "candidate_only": True,
                        "input_text": payload.get("input_text"),
                        "seed": int(payload.get("seed", 1)),
                        "reference_attempts": reference_attempts,
                        "image_provider_contract": payload.get("image_provider_contract"),
                    "image_provider": selected_attempt.get("image_provider", "flux1-schnell"),
                    "image_provider_metadata": selected_attempt.get("image_provider_metadata"),
                    "selected_reference_job_id": selected_attempt.get(
                            "reference_job_id"
                        ),
                        "reference_image_path": selected_attempt.get(
                            "prepared_image_path"
                        ),
                        "scene_dna_candidate_selection": scene_dna_candidate_selection,
                        "persistent_evidence_root": str(
                            persistent_job_evidence_root
                        ),
                        "processing_contract": selected_attempt.get("processing_contract"),
                        "selected_reference_evidence": selected_attempt.get(
                            "persistent_evidence"
                        ),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return metadata_path

        source_image_path = Path(str(selected_attempt["source_image_path"]))
        image_path = Path(str(selected_attempt["prepared_image_path"]))
        pipeline, torch, o_voxel = self._pipeline_instance()
        seed = int(payload.get("seed", 1))
        requested_pipeline_type = str(payload.get("pipeline_type") or self.args.pipeline_type)
        requested_preprocess_image = bool(
            payload.get("preprocess_image", self.args.trellis_preprocess_image)
        )
        source_image = Image.open(image_path)
        source_has_transparency = bool(
            source_image.mode == "RGBA"
            and np.any(np.asarray(source_image, dtype=np.uint8)[:, :, 3] < 250)
        )
        # TRELLIS preprocessing uses an existing alpha channel directly, crops to
        # the object, and multiplies RGB by alpha. Skipping it on our prepared
        # transparent references makes the hidden cyan/pink RGB backdrop become a
        # large reconstructed plane. Force the safe alpha-aware path in that case.
        preprocess_image = bool(requested_preprocess_image or source_has_transparency)
        image = source_image.convert("RGBA")
        pipeline_run_attempts: list[dict[str, Any]] = []
        mesh = None
        pipeline_type = requested_pipeline_type
        pipeline_candidates = self._pipeline_fallback_types(requested_pipeline_type)
        simplify_limit = int(payload.get("simplify_limit", self.args.simplify_limit))
        for attempt_index, candidate_pipeline_type in enumerate(pipeline_candidates):
            attempt: dict[str, Any] = {
                "pipeline_type": candidate_pipeline_type,
                "fallback": attempt_index > 0,
                "simplify_limit": simplify_limit,
            }
            start = time.time()
            meshes = None
            candidate_mesh = None
            try:
                meshes = pipeline.run(
                    image,
                    num_samples=1,
                    seed=seed,
                    pipeline_type=candidate_pipeline_type,
                    preprocess_image=preprocess_image,
                    sparse_structure_sampler_params={
                        "steps": int(payload.get("sparse_steps", self.args.sparse_steps)),
                        "guidance_strength": float(payload.get("sparse_guidance", self.args.sparse_guidance)),
                    },
                    shape_slat_sampler_params={
                        "steps": int(payload.get("shape_steps", self.args.shape_steps)),
                        "guidance_strength": float(payload.get("shape_guidance", self.args.shape_guidance)),
                    },
                    tex_slat_sampler_params={
                        "steps": int(payload.get("tex_steps", self.args.tex_steps)),
                        "guidance_strength": float(payload.get("tex_guidance", self.args.tex_guidance)),
                    },
                )
                candidate_mesh = meshes[0]
                candidate_mesh.simplify(simplify_limit)
                attempt["ok"] = True
                attempt["elapsed_seconds"] = round(time.time() - start, 3)
                pipeline_run_attempts.append(attempt)
                pipeline_type = candidate_pipeline_type
                mesh = candidate_mesh
                break
            except Exception as exc:
                attempt["ok"] = False
                attempt["elapsed_seconds"] = round(time.time() - start, 3)
                attempt["error"] = f"{type(exc).__name__}: {exc}"
                attempt["traceback_tail"] = traceback.format_exc()[-4000:]
                pipeline_run_attempts.append(attempt)
                meshes = None
                candidate_mesh = None
                gc.collect()
                if hasattr(torch, "cuda") and torch.cuda.is_available():
                    torch.cuda.empty_cache()
                if not self._is_cuda_oom(exc) or attempt_index == len(pipeline_candidates) - 1:
                    metadata_path.write_text(
                        json.dumps(
                            {
                                "job_id": job_id,
                                "status": "failed",
                                "failed_stage": "trellis2_pipeline_run_or_simplify",
                                "input_text": payload.get("input_text"),
                                "seed": seed,
                                "requested_pipeline_type": requested_pipeline_type,
                                "pipeline_type": candidate_pipeline_type,
                                "preprocess_image": preprocess_image,
                                "requested_preprocess_image": requested_preprocess_image,
                                "source_has_transparency": source_has_transparency,
                                "source_image_path": str(source_image_path),
                                "reference_image_path": str(image_path),
                                "reference_attempts": reference_attempts,
                                "image_provider_contract": payload.get("image_provider_contract"),
                    "image_provider": selected_attempt.get("image_provider", "flux1-schnell"),
                    "image_provider_metadata": selected_attempt.get("image_provider_metadata"),
                    "selected_reference_job_id": selected_attempt.get("reference_job_id"),
                                "scene_dna_candidate_selection": scene_dna_candidate_selection,
                                "persistent_evidence_root": str(
                                    persistent_job_evidence_root
                                ),
                                "processing_contract": selected_attempt.get("processing_contract"),
                                "selected_reference_evidence": selected_attempt.get(
                                    "persistent_evidence"
                                ),
                                "alpha_quality_ok": selected_attempt.get("alpha_quality_ok"),
                                "pipeline_run_attempts": pipeline_run_attempts,
                                "glb_path": None,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    raise
                print(
                    f"[trellis2] pipeline/simplify CUDA OOM for {job_id} with "
                    f"{candidate_pipeline_type}; retrying lower pipeline",
                    flush=True,
                )
        if mesh is None:
            raise RuntimeError("Trellis2 pipeline returned no mesh")
        postprocess_attempts: list[dict[str, Any]] = []
        try:
            glb, postprocess_attempts = self._postprocess_to_glb_with_retries(o_voxel, mesh, payload)
        except Exception as exc:
            metadata_path.write_text(
                json.dumps(
                    {
                        "job_id": job_id,
                        "status": "failed",
                        "failed_stage": "trellis2_postprocess_to_glb",
                        "input_text": payload.get("input_text"),
                        "seed": seed,
                        "requested_pipeline_type": requested_pipeline_type,
                        "pipeline_type": pipeline_type,
                        "preprocess_image": preprocess_image,
                        "requested_preprocess_image": requested_preprocess_image,
                        "source_has_transparency": source_has_transparency,
                        "source_image_path": str(source_image_path),
                        "reference_image_path": str(image_path),
                        "reference_attempts": reference_attempts,
                        "image_provider_contract": payload.get("image_provider_contract"),
                    "image_provider": selected_attempt.get("image_provider", "flux1-schnell"),
                    "image_provider_metadata": selected_attempt.get("image_provider_metadata"),
                    "selected_reference_job_id": selected_attempt.get("reference_job_id"),
                        "scene_dna_candidate_selection": scene_dna_candidate_selection,
                        "persistent_evidence_root": str(
                            persistent_job_evidence_root
                        ),
                        "processing_contract": selected_attempt.get("processing_contract"),
                        "selected_reference_evidence": selected_attempt.get(
                            "persistent_evidence"
                        ),
                        "alpha_quality_ok": selected_attempt.get("alpha_quality_ok"),
                        "pipeline_run_attempts": pipeline_run_attempts,
                        "postprocess_attempts": postprocess_attempts,
                        "postprocess_error": f"{type(exc).__name__}: {exc}",
                        "postprocess_traceback_tail": traceback.format_exc()[-4000:],
                        "glb_path": None,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise
        glb_webp = bool(payload.get("glb_webp", self.args.glb_webp))
        glb.export(output_glb, extension_webp=glb_webp)
        metadata_path.write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "status": "done",
                    "input_text": payload.get("input_text"),
                    "seed": seed,
                    "requested_pipeline_type": requested_pipeline_type,
                    "pipeline_type": pipeline_type,
                    "preprocess_image": preprocess_image,
                    "requested_preprocess_image": requested_preprocess_image,
                    "source_has_transparency": source_has_transparency,
                    "glb_webp": glb_webp,
                    "source_image_path": str(source_image_path),
                    "reference_image_path": str(image_path),
                    "reference_attempts": reference_attempts,
                    "image_provider_contract": payload.get("image_provider_contract"),
                    "image_provider": selected_attempt.get("image_provider", "flux1-schnell"),
                    "image_provider_metadata": selected_attempt.get("image_provider_metadata"),
                    "selected_reference_job_id": selected_attempt.get("reference_job_id"),
                    "scene_dna_candidate_selection": scene_dna_candidate_selection,
                    "persistent_evidence_root": str(
                        persistent_job_evidence_root
                    ),
                    "processing_contract": selected_attempt.get("processing_contract"),
                    "selected_reference_evidence": selected_attempt.get(
                        "persistent_evidence"
                    ),
                    "alpha_quality_ok": selected_attempt.get("alpha_quality_ok"),
                    "pipeline_run_attempts": pipeline_run_attempts,
                    "postprocess_attempts": postprocess_attempts,
                    "glb_path": str(output_glb),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()
        return output_glb


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def build_handler(
    jobs: JobStore,
    runtime: Trellis2BridgeRuntime,
    broker: HeavyJobBroker | None = None,
):
    metadata_delivery_lock = threading.Lock()
    metadata_delivery_count = 0
    recycle_pending = threading.Event()

    def schedule_process_recycle_after_metadata_delivery() -> None:
        """Optionally recycle only after the client has fetched job metadata.

        Repeatedly unloading and rebuilding the full TRELLIS pipeline in one
        cgroup can accumulate reclaim pressure even when Python references and
        CUDA caches have been released.  The opt-in process boundary gives the
        next candidate a fresh cgroup while preserving the HTTP contract: both
        the GLB and metadata have already been delivered before exit is queued.
        A supervising service must be configured to restart the process.
        """

        nonlocal metadata_delivery_count
        limit = int(getattr(runtime.args, "exit_after_metadata_responses", 0))
        if limit <= 0:
            return
        with metadata_delivery_lock:
            metadata_delivery_count += 1
            should_exit = metadata_delivery_count >= limit
        if not should_exit:
            return
        # Close the admission gate before queuing the exit.  Without this,
        # a fast client can submit the next job during the short grace period;
        # that in-memory job id disappears when the supervised process restarts.
        recycle_pending.set()
        print(
            "[trellis2] scheduling clean process recycle after metadata delivery",
            flush=True,
        )
        timer = threading.Timer(1.5, os._exit, args=(0,))
        timer.daemon = True
        timer.start()

    class Handler(BaseHTTPRequestHandler):
        server_version = "SAGETrellis2Bridge/0.1"
        recycle_pending_event = recycle_pending
        schedule_process_recycle_for_test = staticmethod(
            schedule_process_recycle_after_metadata_delivery
        )

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str) -> None:
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                route_path, requested_provider = provider_route(parsed.path)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            parsed = parsed._replace(path=route_path)
            if requested_provider and route_path.startswith("/job/"):
                route_job_id = route_path.split("/")[2]
                route_job = jobs.get(route_job_id)
                if route_job and route_job.get("image_provider") != requested_provider:
                    self._send_json(404, {"error": "job does not belong to this image provider"})
                    return
            if route_path.startswith("/job/"):
                checkpoint_job = jobs.get(route_path.split("/")[2])
                if checkpoint_job and checkpoint_job.get("status") == "interrupted":
                    self._send_json(410, {
                        "status": "interrupted", "job_id": route_path.split("/")[2],
                        "image_provider": checkpoint_job.get("image_provider"),
                        "resume_path": route_path.split("/metadata")[0] + "/resume",
                    })
                    return
            if parsed.path in {"/", "/health"}:
                self._send_json(
                    200,
                    {
                        "status": "healthy",
                        "service": "trellis2-flux-bridge",
                        "gpu_available": True,
                        "trellis_model": runtime.args.trellis_model,
                        "flux_server_url": runtime.args.flux_server_url,
                        "flux_profile": runtime.args.flux_profile,
                        "image_provider": requested_provider or runtime.args.image_provider,
                        "image_provider_contract": runtime.image_provider_contract(requested_provider or runtime.args.image_provider),
                        "builtin_imagegen_url": runtime.args.builtin_imagegen_url,
                        "heavy_job_broker": broker.snapshot() if broker else None,
                    },
                )
                return
            if parsed.path == "/api/v1/models":
                self._send_json(
                    200,
                    {
                        "data": [
                            {
                                "id": "trellis2-flux-bridge",
                                "trellis_model": runtime.args.trellis_model,
                                "pipeline_type": runtime.args.pipeline_type,
                            }
                        ]
                    },
                )
                return
            if parsed.path.startswith("/job/") and parsed.path.endswith("/metadata"):
                parts = [part for part in parsed.path.split("/") if part]
                if len(parts) != 3:
                    self._send_json(404, {"error": "not found"})
                    return
                job_id = parts[1]
                job = jobs.get(job_id)
                if job is None:
                    self._send_json(404, {"error": "job not found"})
                    return
                metadata_path = Path(str(job.get("metadata_path") or Path(runtime.args.output_dir) / f"{job_id}.json"))
                if not metadata_path.exists():
                    self._send_json(202 if job.get("status") in {"processing", "waiting_for_image_provider"} else 404, {"error": "metadata not ready"})
                    return
                self._send_file(metadata_path, "application/json")
                schedule_process_recycle_after_metadata_delivery()
                return
            if parsed.path.startswith("/job/"):
                job_id = parsed.path.rsplit("/", 1)[-1]
                job = jobs.get(job_id)
                if job is None:
                    self._send_json(404, {"error": "job not found"})
                    return
                if job.get("status") == "done":
                    self._send_file(
                        Path(str(job["glb_path"])),
                        str(job.get("content_type") or "model/gltf-binary"),
                    )
                    return
                if job.get("status") == "failed":
                    self._send_json(
                        500,
                        {
                            "error": job.get("error", "unknown error"),
                            "error_log": job.get("error_log"),
                        },
                    )
                    return
                self._send_json(202, {
                    "status": job.get("status", "processing"),
                    "resume_path": f"/job/{job_id}/resume" if job.get("status") == "waiting_for_image_provider" else None,
                })
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                route_path, requested_provider = provider_route(parsed.path)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            parsed = parsed._replace(path=route_path)
            resume_match = re.fullmatch(r"/job/([A-Za-z0-9_-]+)/resume", parsed.path)
            if parsed.path != "/generate" and resume_match is None:
                self._send_json(404, {"error": "not found"})
                return
            if recycle_pending.is_set():
                self._send_json(
                    503,
                    {
                        "error": "bridge process is draining before supervised restart",
                        "retryable": True,
                    },
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                if not isinstance(payload, dict):
                    raise ValueError("Generation request must be an object")
                if resume_match:
                    if payload:
                        raise ValueError("Resume uses the stored request; body must be empty")
                    previous = jobs.get(resume_match.group(1))
                    if not previous or previous.get("status") not in {"interrupted", "waiting_for_image_provider"}:
                        raise ValueError("Job is not an interrupted resumable job")
                    payload = dict(previous["request"])
                if requested_provider and payload.get("image_provider", requested_provider) != requested_provider:
                    raise ValueError("Image provider in URL conflicts with request body")
                provider = requested_provider or str(payload.get("image_provider", getattr(runtime.args, "image_provider", "builtin_imagegen")))
                if provider not in BRIDGE_IMAGE_PROVIDERS:
                    raise ValueError("Unsupported image provider")
                payload["image_provider"] = provider
                if hasattr(runtime, "image_provider_contract"):
                    current_contract = runtime.image_provider_contract(provider)
                    stored_contract = payload.get("image_provider_contract")
                    if resume_match and stored_contract is None:
                        raise ValueError("Interrupted job lacks its original image provider contract")
                    if stored_contract is not None and stored_contract != current_contract:
                        raise ValueError("Image provider configuration changed; request contract mismatch")
                    payload["image_provider_contract"] = current_contract
                job_id = resume_match.group(1) if resume_match else uuid.uuid4().hex
                admission = broker.acquire(job_id) if broker else {"accepted": True}
                if not admission.get("accepted"):
                    self._send_json(
                        429,
                        {
                            "error": "heavy job admission rejected",
                            "retryable": bool(admission.get("retryable", True)),
                            "admission": admission,
                        },
                    )
                    return
                jobs.create(job_id, image_provider=provider, request=payload)

                def worker() -> None:
                    heartbeat_stop = threading.Event()
                    heartbeat_thread = None
                    if broker is not None:
                        def pulse() -> None:
                            interval = max(1.0, broker.lease_ttl_seconds / 3.0)
                            while not heartbeat_stop.wait(interval):
                                if not broker.heartbeat(job_id):
                                    return
                        heartbeat_thread = threading.Thread(target=pulse, daemon=True)
                        heartbeat_thread.start()
                    try:
                        glb_path = runtime.generate(payload, job_id)
                        metadata_path = Path(runtime.args.output_dir) / f"{job_id}.json"
                        content_type = (
                            "application/json"
                            if glb_path.suffix.lower() == ".json"
                            else "model/gltf-binary"
                        )
                        jobs.update(
                            job_id,
                            status="done",
                            glb_path=str(glb_path),
                            content_type=content_type,
                            metadata_path=str(metadata_path),
                            completed_at=time.time(),
                        )
                    except Exception as exc:  # pragma: no cover - runtime failures are reported over HTTP
                        trace = traceback.format_exc()
                        error_log = Path(runtime.args.output_dir) / f"{job_id}.error.txt"
                        error_log.parent.mkdir(parents=True, exist_ok=True)
                        error_log.write_text(trace, encoding="utf-8")
                        metadata_path = Path(runtime.args.output_dir) / f"{job_id}.json"
                        jobs.update(
                            job_id,
                            status=("waiting_for_image_provider" if isinstance(exc, TimeoutError) and str(exc).startswith("waiting_for_image_provider:") else "failed"),
                            error=str(exc),
                            error_log=str(error_log),
                            metadata_path=str(metadata_path) if metadata_path.exists() else None,
                            completed_at=time.time(),
                        )
                        print(f"[trellis2] job {job_id} failed:\n{trace}", flush=True)
                    finally:
                        heartbeat_stop.set()
                        if heartbeat_thread is not None:
                            heartbeat_thread.join(timeout=1.0)
                        if broker is not None:
                            broker.release(job_id)
                        runtime.cleanup_after_job()

                threading.Thread(target=worker, daemon=True).start()
                self._send_json(202, {"job_id": job_id, "status": "processing", "message": "Processing started"})
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[trellis2] {self.address_string()} {fmt % args}", flush=True)

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve SAGE TRELLIS API via local Flux plus TRELLIS.2.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--image-provider", choices=BRIDGE_IMAGE_PROVIDERS, default="builtin_imagegen")
    parser.add_argument("--builtin-imagegen-url", default="http://127.0.0.1:8084")
    parser.add_argument("--builtin-imagegen-timeout", type=float, default=1800.0)
    parser.add_argument("--flux-server-url", default="http://127.0.0.1:8083")
    parser.add_argument("--flux-profile", choices=["flux1-schnell", "flux2-klein", "custom"], default="flux1-schnell")
    parser.add_argument("--trellis-repo", default="/home/xy/PAT3D/pat3d_stage2/vendor/TRELLIS.2")
    parser.add_argument("--trellis-model", default="/data/xy/pat3d_stage2_data/models/trellis2_primary")
    parser.add_argument("--output-dir", default="/data/xy/SAGE_repro/trellis2_bridge")
    parser.add_argument(
        "--persistent-evidence-dir",
        default="",
        help=(
            "Non-temporary root for raw Flux RGB, prepared RGBA, masks, and "
            "hash manifests. Required when --output-dir is under /tmp or /var/tmp."
        ),
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--pipeline-type", default="1024_cascade", choices=["512", "1024", "1024_cascade", "1536_cascade"])
    parser.add_argument(
        "--trellis-low-vram",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Override the pipeline low-VRAM policy. --no-trellis-low-vram "
            "moves the selected TRELLIS models to the target device after load, "
            "reducing host RSS on GPUs with sufficient VRAM."
        ),
    )
    parser.add_argument("--trellis-preprocess-image", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--flux-width", type=int, default=768)
    parser.add_argument("--flux-height", type=int, default=768)
    parser.add_argument("--flux-steps", type=int)
    parser.add_argument("--flux-guidance-scale", type=float)
    parser.add_argument("--flux-max-sequence-length", type=int)
    parser.add_argument(
        "--flux-background-mode",
        choices=["contrast", "gray", "white"],
        default="white",
        help=(
            "Background used for generated isolated references. Pure white is "
            "the production default; gray/contrast modes are diagnostic-only."
        ),
    )
    parser.add_argument("--flux-retry-count", type=int, default=2)
    parser.add_argument("--flux-timeout", type=float, default=600.0)
    parser.add_argument("--sparse-steps", type=int, default=12)
    parser.add_argument("--sparse-guidance", type=float, default=7.5)
    parser.add_argument("--shape-steps", type=int, default=12)
    parser.add_argument("--shape-guidance", type=float, default=7.5)
    parser.add_argument("--tex-steps", type=int, default=12)
    parser.add_argument("--tex-guidance", type=float, default=1.0)
    parser.add_argument("--simplify-limit", type=int, default=1_048_576)
    parser.add_argument("--decimation-target", type=int, default=500_000)
    parser.add_argument("--texture-size", type=int, default=2048)
    parser.add_argument("--glb-webp", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--alpha-mode", choices=["rembg", "threshold", "none"], default="rembg")
    parser.add_argument("--alpha-fallback-threshold", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--rmbg-model", default="/data/xy/pat3d_stage2_data/models/rmbg_2_0")
    parser.add_argument("--rmbg-module-root", default="/data/xy/pat3d_stage2_data/cache/hf_home/modules")
    parser.add_argument("--rmbg-offload-cpu", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--alpha-threshold", type=float, default=48.0)
    parser.add_argument("--bg-saturation-threshold", type=float, default=28.0)
    parser.add_argument("--bg-value-threshold", type=float, default=222.0)
    parser.add_argument("--alpha-min-component-ratio", type=float, default=0.00025)
    parser.add_argument("--alpha-morph-kernel", type=int, default=5)
    parser.add_argument("--alpha-dilate", type=int, default=1)
    parser.add_argument("--alpha-bbox-threshold", type=int, default=24)
    parser.add_argument("--alpha-content-scale", type=float, default=0.86)
    parser.add_argument("--alpha-quality-check", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--alpha-require-quality", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--background-isolation-require-clean",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Fail before TRELLIS when the generated white source, exact-white "
            "normalized preview, or exposed-support background-gap contract fails."
        ),
    )
    parser.add_argument("--alpha-min-foreground-ratio", type=float, default=0.012)
    parser.add_argument("--alpha-max-foreground-ratio", type=float, default=0.68)
    parser.add_argument("--alpha-max-border-foreground-ratio", type=float, default=0.015)
    parser.add_argument("--white-background-alpha-max", type=int, default=8)
    parser.add_argument("--white-background-minimum-channel", type=float, default=232.0)
    parser.add_argument("--white-background-maximum-chroma-range", type=float, default=18.0)
    parser.add_argument("--white-background-minimum-fraction", type=float, default=0.96)
    parser.add_argument("--white-background-maximum-median-deviation", type=float, default=18.0)
    parser.add_argument("--white-base-quality-check", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--white-base-require-clean", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--white-base-auto-repair", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--white-base-bottom-start-ratio", type=float, default=0.58)
    parser.add_argument("--white-base-top-slack-ratio", type=float, default=0.035)
    parser.add_argument("--white-base-min-width-ratio", type=float, default=0.50)
    parser.add_argument("--white-base-max-height-ratio", type=float, default=0.45)
    parser.add_argument("--white-base-bedlike-max-height-ratio", type=float, default=0.20)
    parser.add_argument("--white-base-min-aspect-ratio", type=float, default=1.55)
    parser.add_argument("--white-base-min-area-ratio", type=float, default=0.010)
    parser.add_argument("--white-base-saturation-threshold", type=float, default=72.0)
    parser.add_argument("--white-base-value-threshold", type=float, default=170.0)
    parser.add_argument("--white-base-rgb-delta-threshold", type=float, default=52.0)
    parser.add_argument("--white-base-score-penalty", type=float, default=0.65)
    parser.add_argument("--white-base-support-band-height-ratio", type=float, default=0.04)
    parser.add_argument("--white-base-max-support-occupancy-ratio", type=float, default=0.55)
    parser.add_argument("--connected-base-min-width-ratio", type=float, default=0.72)
    parser.add_argument("--connected-base-max-height-ratio", type=float, default=0.24)
    parser.add_argument("--connected-base-min-aspect-ratio", type=float, default=6.0)
    parser.add_argument("--connected-base-min-bottom-ratio", type=float, default=0.72)
    parser.add_argument("--support-gap-horizontal-inset-ratio", type=float, default=0.10)
    parser.add_argument("--support-gap-minimum-depth-ratio", type=float, default=0.11)
    parser.add_argument("--support-gap-minimum-open-column-fraction", type=float, default=0.30)
    parser.add_argument("--support-gap-score-penalty", type=float, default=0.65)
    parser.add_argument("--white-base-repair-start-ratio", type=float, default=0.64)
    parser.add_argument("--white-base-repair-min-row-width-ratio", type=float, default=0.22)
    parser.add_argument("--white-base-repair-plant-min-row-width-ratio", type=float, default=0.38)
    parser.add_argument("--white-base-repair-plant-center-keep-width-ratio", type=float, default=0.56)
    parser.add_argument("--white-base-repair-min-area-ratio", type=float, default=0.001)
    parser.add_argument("--white-base-repair-max-passes", type=int, default=3)
    parser.add_argument(
        "--white-base-repair-max-removed-foreground-fraction",
        type=float,
        default=0.35,
    )
    parser.add_argument(
        "--white-base-repair-max-upper-removed-fraction",
        type=float,
        default=0.005,
    )
    parser.add_argument(
        "--alpha-max-visible-chroma-spill-fraction",
        type=float,
        default=0.12,
    )
    parser.add_argument(
        "--alpha-max-chroma-cleanup-removed-fraction",
        type=float,
        default=0.12,
    )
    parser.add_argument(
        "--scene-dna-form-scoring",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--scene-dna-semantic-scoring",
        choices=["off", "optional", "required"],
        default="off",
    )
    parser.add_argument(
        "--scene-dna-semantic-model",
        default="google/siglip2-base-patch16-naflex",
    )
    parser.add_argument("--scene-dna-semantic-device", default="cpu")
    parser.add_argument("--scene-dna-anchor-manifest")
    parser.add_argument(
        "--scene-dna-anchor-model",
        default="facebook/dinov3-vitl16-pretrain-lvd1689m",
    )
    parser.add_argument("--scene-dna-anchor-device", default="cpu")
    parser.add_argument("--scene-dna-uncertainty-margin", type=float, default=0.03)
    parser.add_argument(
        "--scene-dna-form-improvement-guard",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Development-only conservative selector: replace the legacy candidate "
            "only when the SceneDNA candidate has a measured form-score gain."
        ),
    )
    parser.add_argument(
        "--scene-dna-vnext-selector",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Development-only category-independent selector that balances 2D-to-3D "
            "generability, part completeness, image hygiene, and current style evidence."
        ),
    )
    parser.add_argument(
        "--scene-dna-minimum-form-improvement",
        type=float,
        default=0.08,
        help="Minimum opt-in form-score delta over the legacy candidate.",
    )
    parser.add_argument(
        "--scene-dna-unload-scorers",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--scene-dna-release-pipeline-before-scoring",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Opt in to dropping a cached TRELLIS pipeline before SceneDNA "
            "reference scoring so scorer and generator host-memory peaks do "
            "not overlap; the pipeline is rebuilt before 3D generation."
        ),
    )
    parser.add_argument(
        "--exit-after-metadata-responses",
        type=int,
        default=0,
        help=(
            "Opt in to exiting cleanly after this many completed-job metadata "
            "responses. Use only under a restart supervisor; zero disables it."
        ),
    )
    parser.add_argument(
        "--heavy-job-lease-state",
        default="",
        help="Shared JSON lease state; defaults under --output-dir.",
    )
    parser.add_argument("--heavy-job-lease-ttl", type=float, default=120.0)
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument(
        "--maximum-cgroup-memory-gib",
        type=float,
        default=16.0,
        help=(
            "Largest finite memory.max accepted by the heavy-job resource gate. "
            "Set this explicitly to the service MemoryMax when a model needs more "
            "than the conservative 16 GiB default."
        ),
    )
    parser.add_argument(
        "--require-bounded-cgroup",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--require-nvml-admission",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--remesh", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--remesh-band", type=int, default=1)
    parser.add_argument("--remesh-project", type=int, default=0)
    args = parser.parse_args()
    if args.flux_steps is None:
        args.flux_steps = 4
    if args.flux_guidance_scale is None:
        args.flux_guidance_scale = 1.0 if args.flux_profile == "flux2-klein" else 0.0
    if args.flux_max_sequence_length is None and args.flux_profile == "flux2-klein":
        args.flux_max_sequence_length = 512
    return args


def main() -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    args = parse_args()
    if args.builtin_imagegen_timeout <= 0:
        raise ValueError("--builtin-imagegen-timeout must be positive")
    if _is_loopback_url(args.builtin_imagegen_url) and urlparse(args.builtin_imagegen_url).port == int(args.port):
        raise ValueError("Builtin image provider and TRELLIS bridge must use different ports")
    flux_url = urlparse(args.flux_server_url)
    flux_port = flux_url.port
    if _is_loopback_url(args.flux_server_url) and flux_port == int(args.port):
        raise ValueError(
            f"Bridge port {args.port} conflicts with flux-server-url {args.flux_server_url}; "
            "run Flux and the TRELLIS bridge on different ports."
        )
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    runtime = Trellis2BridgeRuntime(args)
    # Fail during service startup, before accepting heavy jobs, when evidence
    # would otherwise be volatile.
    evidence_root = runtime._persistent_evidence_root()
    jobs = JobStore(evidence_root / "bridge_jobs")
    lease_path = Path(args.heavy_job_lease_state) if args.heavy_job_lease_state else Path(args.output_dir) / "heavy_job_lease.json"
    broker = HeavyJobBroker(
        lease_path,
        lease_ttl_seconds=float(args.heavy_job_lease_ttl),
        gpu_index=int(args.gpu_index),
        require_nvml=bool(args.require_nvml_admission),
        require_bounded_cgroup=bool(args.require_bounded_cgroup),
        maximum_cgroup_memory_bytes=int(
            float(args.maximum_cgroup_memory_gib) * 1024**3
        ),
    )
    httpd = ThreadingHTTPServer((args.host, args.port), build_handler(jobs, runtime, broker))
    print(f"[trellis2] serving on http://{args.host}:{args.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
