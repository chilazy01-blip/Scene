"""Durable handoff from the image HTTP API to a Codex tool executor.

This module never generates images. An available Codex session reads a pending
request, claims it, invokes ``image_gen.imagegen`` with its exact prompt, and
imports that tool's image. In the session's absence jobs remain waiting. Local
receipts attest to that handoff; they are not model-provider signed receipts.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from typing import Any, Callable, Iterator


BUILTIN_IMAGE_PROVIDER = "builtin_imagegen"
DEFAULT_IMAGE_PROVIDER = BUILTIN_IMAGE_PROVIDER
IMAGE_PROVIDERS = (BUILTIN_IMAGE_PROVIDER, "flux1-schnell")
DEFAULT_BUILTIN_SPOOL = Path("/data/wsj/main/scene_runs/builtin_imagegen_jobs")
BUILTIN_METADATA_SCHEMA = "builtin_imagegen_artifact_v1"
MAX_IMAGE_BYTES = 64 * 1024 * 1024
_JOB_ID = re.compile(r"builtin_[0-9a-f]{64}\Z")


class ImageProviderError(ValueError):
    """A request or executor transition violates the handoff contract."""


class ImageProviderIntegrityError(ImageProviderError):
    """A durable record or image no longer matches its committed evidence."""


class ImageProviderConflict(ImageProviderError):
    """Another claim or a terminal result already owns this request."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _positive_seconds(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ImageProviderError(f"{name} must be finite and positive")
    return value


def _atomic_write(path: Path, body: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _image_info(body: bytes) -> dict[str, Any]:
    # Pillow is loaded only on import, never for a waiting HTTP service. Decode
    # both verifies the container and rejects truncated/compressed image bombs.
    from PIL import Image, UnidentifiedImageError

    if not body or len(body) > MAX_IMAGE_BYTES:
        raise ImageProviderError("source image is empty or exceeds 64 MiB")
    try:
        with Image.open(BytesIO(body)) as image:
            image_format = image.format
            width, height = image.size
            if image_format not in {"PNG", "JPEG", "WEBP"}:
                raise ImageProviderError("source image must be PNG, JPEG, or WEBP")
            if width * height > 40_000_000 or min(width, height) < 1:
                raise ImageProviderError("source image dimensions exceed the import limit")
            if getattr(image, "n_frames", 1) != 1:
                raise ImageProviderError("animated source images are not accepted")
            image.verify()
        with Image.open(BytesIO(body)) as image:
            image.load()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, SyntaxError) as exc:
        raise ImageProviderError(f"invalid source image: {exc}") from exc
    return {
        "width": width,
        "height": height,
        "mime_type": {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[image_format],
        "format": image_format,
    }


class ImageCandidateJobSpool:
    """Content-addressed requests, leased executor claims and verified results.

    A spool-wide flock serializes writers across processes and HTTP threads.
    Its private HMAC key detects record editing and accidental cache corruption;
    it does not establish trust against an attacker with the same OS account.
    A metadata commit precedes the terminal state commit so interrupted imports
    recover without invoking the image tool a second time.
    """

    def __init__(self, root: Path | str = DEFAULT_BUILTIN_SPOOL, *, clock: Callable[[], float] = time.time) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self._locked():
            key_path = self.root / ".integrity.key"
            if not key_path.exists():
                if any(self.root.glob("builtin_*/request.json")):
                    raise ImageProviderIntegrityError("spool integrity key missing; existing jobs cannot be re-signed")
                _atomic_write(key_path, secrets.token_bytes(32))
            self._key = key_path.read_bytes()
            if len(self._key) != 32:
                raise ImageProviderIntegrityError("invalid spool integrity key")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with (self.root / ".spool.lock").open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _directory(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise ImageProviderError("invalid builtin job id")
        path = self.root / job_id
        if path.is_symlink():
            raise ImageProviderIntegrityError("job directory must not be a symlink")
        return path

    def _sign(self, record: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in record.items() if key != "record_hmac"}
        result["record_hmac"] = hmac.new(self._key, canonical_json(result), hashlib.sha256).hexdigest()
        return result

    def _write(self, path: Path, record: dict[str, Any]) -> None:
        _atomic_write(path, canonical_json(self._sign(record)))

    def _read(self, path: Path) -> dict[str, Any]:
        if path.is_symlink():
            raise ImageProviderIntegrityError(f"record must not be a symlink: {path.name}")
        try:
            record = json.loads(path.read_bytes())
            if not isinstance(record, dict):
                raise ValueError("expected object")
            actual = record.get("record_hmac")
            expected = self._sign(record)["record_hmac"]
            if not isinstance(actual, str) or not hmac.compare_digest(actual, expected):
                raise ValueError("signature mismatch")
            return record
        except (OSError, ValueError, TypeError) as exc:
            raise ImageProviderIntegrityError(f"invalid durable record {path.name}: {exc}") from exc

    @staticmethod
    def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ImageProviderError("generation request must be an object")
        value = json.loads(canonical_json(payload))
        prompt = value.get("prompt", value.get("input_text"))
        if not isinstance(prompt, str) or not prompt.strip():
            raise ImageProviderError("generation request requires a nonempty prompt")
        if len(prompt.encode("utf-8")) > 100_000:
            raise ImageProviderError("prompt exceeds 100000 bytes")
        if value.get("provider", BUILTIN_IMAGE_PROVIDER) != BUILTIN_IMAGE_PROVIDER:
            raise ImageProviderError("builtin spool cannot execute another provider")
        if value.get("model") or value.get("backend_model_id") or value.get("requested_model"):
            raise ImageProviderError("builtin tool exposes no model selection or verified backend model id")
        if value.get("reference_image_path") or value.get("input_image_path"):
            raise ImageProviderError("builtin candidate spool accepts new image requests only")
        value.pop("input_text", None)
        value["prompt"] = prompt
        value["provider"] = BUILTIN_IMAGE_PROVIDER
        return value

    def _initial_state(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": "builtin_imagegen_job_state_v1",
            "job_id": request["job_id"],
            "request_sha256": request["request_sha256"],
            "status": "waiting_for_image_provider",
            "waiting_reason": "requires_codex_session_with_image_gen.imagegen",
            "created_at": request["created_at"],
            "deadline_at": request.get("initial_deadline_at"),
            "claim": None,
            "attempts": [],
            "retries": [],
        }

    def submit(self, payload: dict[str, Any], *, timeout_seconds: float | None = None) -> dict[str, Any]:
        normalized = self._normalize(payload)
        if timeout_seconds is not None:
            timeout_seconds = _positive_seconds(timeout_seconds, "timeout_seconds")
        request_hash = sha256_bytes(canonical_json(normalized))
        job_id = f"builtin_{request_hash}"
        with self._locked():
            directory = self._directory(job_id)
            if (directory / "request.json").exists():
                request, state = self._load(job_id)
            else:
                created = self.clock()
                request = {
                    "schema": "builtin_imagegen_request_v1",
                    "job_id": job_id,
                    "request_sha256": request_hash,
                    "prompt_sha256": sha256_bytes(normalized["prompt"].encode("utf-8")),
                    "prompt": normalized["prompt"],
                    "provider": BUILTIN_IMAGE_PROVIDER,
                    "input": normalized,
                    "created_at": created,
                    "initial_deadline_at": created + timeout_seconds if timeout_seconds else None,
                }
                state = self._initial_state(request)
                if directory.exists():
                    raise ImageProviderIntegrityError("incomplete job directory exists")
                # Publish request+state together. A missing state after this
                # commit is corruption, never permission to regenerate a job.
                staging = Path(tempfile.mkdtemp(prefix=".initializing_", dir=self.root))
                self._write(staging / "request.json", request)
                self._write(staging / "state.json", state)
                os.replace(staging, directory)
                root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(root_fd)
                finally:
                    os.close(root_fd)
            return self._public(request, state)

    def _load(self, job_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        directory = self._directory(job_id)
        if not (directory / "request.json").exists():
            raise KeyError(job_id)
        request = self._read(directory / "request.json")
        request_hash = sha256_bytes(canonical_json(request["input"]))
        if (request["job_id"] != job_id or job_id != f"builtin_{request_hash}"
                or request["request_sha256"] != request_hash
                or request["prompt"] != request["input"]["prompt"]
                or request["prompt_sha256"] != sha256_bytes(request["prompt"].encode("utf-8"))):
            raise ImageProviderIntegrityError("request identity/hash mismatch")
        if (directory / "state.json").exists():
            state = self._read(directory / "state.json")
        else:
            raise ImageProviderIntegrityError("job has lost its committed state record")
        if state["job_id"] != job_id or state["request_sha256"] != request_hash:
            raise ImageProviderIntegrityError("state belongs to another request")
        if state["status"] == "done":
            self._verified_metadata(request, state)
            return request, state
        if (directory / "metadata.json").exists():
            # A crash after the durable metadata commit must complete that same
            # attempt, even if its lease expires before the process restarts.
            metadata = self._verified_metadata(request, state, recovering=True)
            state = self._complete_state(state, metadata)
            self._write(directory / "state.json", state)
            return request, state
        changed = False
        now = self.clock()
        if state["status"] not in {"failed", "expired"}:
            if state.get("deadline_at") is not None and now >= state["deadline_at"]:
                state.update(status="expired", error="image provider job deadline exceeded", completed_at=now)
                if state.get("claim"):
                    state["attempts"].append({**state["claim"], "outcome": "job_expired", "ended_at": now})
                state["claim"] = None
                changed = True
            elif state.get("claim") and now >= state["claim"]["lease_until"]:
                state["attempts"].append({**state["claim"], "outcome": "claim_expired", "ended_at": now})
                state.update(status="waiting_for_image_provider", claim=None, waiting_reason="previous_executor_claim_expired")
                changed = True
        if changed:
            self._write(directory / "state.json", state)
        return request, state

    def _public(self, request: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        result = {
            key: value for key, value in state.items()
            if key not in {"record_hmac", "claim", "attempts"}
        }
        claim = state.get("claim")
        result.update(
            provider=BUILTIN_IMAGE_PROVIDER,
            prompt=request["prompt"],
            prompt_sha256=request["prompt_sha256"],
            request_path=str(self._directory(request["job_id"]) / "request.json"),
            backend_model_id=None,
            model_identity_status="unverified",
            strict_model_identity_verified=False,
            attempt_count=len(state["attempts"]) + int(claim is not None),
        )
        if claim:
            result["claim"] = {key: value for key, value in claim.items() if key != "token_sha256"}
        return result

    def get(self, job_id: str) -> dict[str, Any]:
        with self._locked():
            return self._public(*self._load(job_id))

    def pending(self) -> list[dict[str, Any]]:
        with self._locked():
            result = []
            for path in sorted(self.root.glob("builtin_*/request.json")):
                request, state = self._load(path.parent.name)
                if state["status"] in {"waiting_for_image_provider", "claimed"}:
                    result.append(self._public(request, state))
            return result

    def claim(self, job_id: str, *, owner: str, lease_seconds: float = 900) -> dict[str, Any]:
        if not isinstance(owner, str) or not owner.strip():
            raise ImageProviderError("claim requires a nonempty executor owner")
        lease_seconds = _positive_seconds(lease_seconds, "lease_seconds")
        with self._locked():
            request, state = self._load(job_id)
            if state["status"] != "waiting_for_image_provider":
                raise ImageProviderConflict(f"job cannot be claimed while {state['status']}")
            token = secrets.token_urlsafe(32)
            now = self.clock()
            state.update(status="claimed", claim={
                "attempt_id": secrets.token_hex(16),
                "owner": owner,
                "claimed_at": now,
                "lease_until": min(now + lease_seconds, state.get("deadline_at") or math.inf),
                "token_sha256": sha256_bytes(token.encode("utf-8")),
            })
            self._write(self._directory(job_id) / "state.json", state)
            return {**self._public(request, state), "claim_token": token, "request": request["input"]}

    @staticmethod
    def _check_claim(state: dict[str, Any], token: str) -> dict[str, Any]:
        claim = state.get("claim")
        if state["status"] != "claimed" or not claim:
            raise ImageProviderConflict(f"job has no live claim (status={state['status']})")
        if not hmac.compare_digest(claim["token_sha256"], sha256_bytes(str(token).encode("utf-8"))):
            raise ImageProviderConflict("claim token does not own this job")
        return claim

    def heartbeat(self, job_id: str, *, claim_token: str, lease_seconds: float = 900) -> dict[str, Any]:
        lease_seconds = _positive_seconds(lease_seconds, "lease_seconds")
        with self._locked():
            request, state = self._load(job_id)
            claim = self._check_claim(state, claim_token)
            claim["lease_until"] = min(self.clock() + lease_seconds, state.get("deadline_at") or math.inf)
            self._write(self._directory(job_id) / "state.json", state)
            return self._public(request, state)

    @staticmethod
    def _complete_state(state: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        state["attempts"].append({**state["claim"], "outcome": "done", "ended_at": metadata["completed_at"]})
        state.update(status="done", claim=None, completed_at=metadata["completed_at"],
                     metadata_sha256=sha256_bytes(canonical_json(metadata)), image_sha256=metadata["image_sha256"])
        state.pop("waiting_reason", None)
        return state

    def fulfil(self, job_id: str, source_image: Path | str, *, claim_token: str,
               request_sha256: str, prompt_sha256: str, tool_call_id: str,
               tool_result_json: Path | str | None = None) -> dict[str, Any]:
        """Import unchanged image bytes from an actual, identified tool call.

        The caller is the trusted Codex executor. ``tool_call_id`` is an
        executor-assigned correlation ID for its invocation, not a vendor's
        signed receipt or a verified backend identity. A supplied raw tool
        result is copied and hash-bound as well.
        """
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            raise ImageProviderError("fulfil requires a correlation ID for the executed image_gen.imagegen invocation")
        source = Path(source_image).expanduser().resolve()
        if source.stat().st_size > MAX_IMAGE_BYTES:
            raise ImageProviderError("source image exceeds 64 MiB")
        body = source.read_bytes()
        image_info = _image_info(body)
        image_hash = sha256_bytes(body)
        tool_result = None
        if tool_result_json is not None:
            tool_result = Path(tool_result_json).read_bytes()
            if len(tool_result) > 4 * 1024 * 1024:
                raise ImageProviderError("tool result JSON exceeds 4 MiB")
            if not isinstance(json.loads(tool_result), dict):
                raise ImageProviderError("tool result JSON must be an object")
        with self._locked():
            request, state = self._load(job_id)
            if request_sha256 != request["request_sha256"] or prompt_sha256 != request["prompt_sha256"]:
                raise ImageProviderIntegrityError("executor request/prompt hash mismatch")
            if state["status"] == "done":
                previous = self._verified_metadata(request, state)
                if (previous["image_sha256"] == image_hash and previous["tool_call_id"] == tool_call_id
                        and previous["claim_token_sha256"] == sha256_bytes(str(claim_token).encode("utf-8"))):
                    return previous
                raise ImageProviderConflict("completed image/attempt is immutable; submit a new candidate input")
            claim = self._check_claim(state, claim_token)
            directory = self._directory(job_id)
            suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[image_info["format"]]
            image_path = directory / f"source{suffix}"
            _atomic_write(image_path, body)
            completed = self.clock()
            if completed >= claim["lease_until"]:
                raise ImageProviderConflict("executor claim expired during image import; renew the claim before importing")
            request_body = (directory / "request.json").read_bytes()
            metadata = {
                "schema": BUILTIN_METADATA_SCHEMA,
                "status": "done",
                "provider": BUILTIN_IMAGE_PROVIDER,
                "transport": "codex_session_tool_spool",
                "job_id": job_id,
                "request_id": request["input"].get("request_id") or job_id,
                "upstream_job_id": request["input"].get("upstream_job_id"),
                "attempt_id": claim["attempt_id"],
                "request_sha256": request_sha256,
                "prompt": request["prompt"],
                "prompt_sha256": prompt_sha256,
                "request_path": str(directory / "request.json"),
                "request_file_sha256": sha256_bytes(request_body),
                "request_file": {"path": str(directory / "request.json"), "bytes": len(request_body), "sha256": sha256_bytes(request_body)},
                "tool": "image_gen.imagegen",
                "tool_call_id": tool_call_id,
                "tool_call_id_source": "executor_correlation_id",
                "executor_owner": claim["owner"],
                "claim_token_sha256": claim["token_sha256"],
                "provenance_verification": "executor_attestation",
                "requested_model": None,
                "backend_model_id": None,
                "model_identity_status": "unverified",
                "strict_model_identity_verified": False,
                "seed": None,
                "seed_supported": False,
                "requested_seed": request["input"].get("seed"),
                "requested_width": request["input"].get("width"),
                "requested_height": request["input"].get("height"),
                "quality": None,
                "deterministic": False,
                "image_path": str(image_path),
                "image_sha256": image_hash,
                "image_bytes": len(body),
                "source_image_path": str(source),
                "source_image_sha256": image_hash,
                "created_at": request["created_at"],
                "claimed_at": claim["claimed_at"],
                "completed_at": completed,
                "elapsed_seconds": round(completed - request["created_at"], 6),
                "tool_result": None,
                **image_info,
            }
            if tool_result is not None:
                tool_result_path = directory / "tool_result.json"
                _atomic_write(tool_result_path, tool_result)
                metadata["tool_result"] = {"path": str(tool_result_path), "sha256": sha256_bytes(tool_result)}
            signed = self._sign(metadata)
            _atomic_write(directory / "metadata.json", canonical_json(signed))
            self._write(directory / "state.json", self._complete_state(state, signed))
            return signed

    def _verified_metadata(self, request: dict[str, Any], state: dict[str, Any], *, recovering: bool = False) -> dict[str, Any]:
        directory = self._directory(request["job_id"])
        metadata = self._read(directory / "metadata.json")
        for key in ("job_id", "request_sha256", "prompt_sha256", "prompt", "provider"):
            if metadata.get(key) != request[key]:
                raise ImageProviderIntegrityError(f"metadata {key} does not match the request")
        if (metadata.get("schema") != BUILTIN_METADATA_SCHEMA
                or metadata.get("backend_model_id") is not None
                or metadata.get("strict_model_identity_verified") is not False
                or metadata.get("model_identity_status") != "unverified"
                or metadata.get("tool") != "image_gen.imagegen"
                or not metadata.get("tool_call_id")):
            raise ImageProviderIntegrityError("metadata provider/tool identity contract mismatch")
        if recovering:
            claim = state.get("claim")
            if (state["status"] != "claimed" or not claim
                    or metadata["attempt_id"] != claim["attempt_id"]
                    or metadata["claim_token_sha256"] != claim["token_sha256"]
                    or metadata["completed_at"] > claim["lease_until"]):
                raise ImageProviderIntegrityError("uncommitted metadata does not belong to the active claim")
        elif (state.get("metadata_sha256") != sha256_bytes(canonical_json(metadata))
              or state.get("image_sha256") != metadata["image_sha256"]):
            raise ImageProviderIntegrityError("metadata differs from the committed result")
        request_body = (directory / "request.json").read_bytes()
        if (metadata["request_file_sha256"] != sha256_bytes(request_body)
                or metadata["request_file"] != {"path": str(directory / "request.json"), "bytes": len(request_body), "sha256": sha256_bytes(request_body)}):
            raise ImageProviderIntegrityError("metadata request-file hash mismatch")
        image_path = Path(metadata["image_path"])
        if image_path.parent != directory or image_path.is_symlink():
            raise ImageProviderIntegrityError("result image path escapes the job directory")
        try:
            image_body = image_path.read_bytes()
        except OSError as exc:
            raise ImageProviderIntegrityError("result image is missing") from exc
        if (sha256_bytes(image_body) != metadata["image_sha256"]
                or metadata["source_image_sha256"] != metadata["image_sha256"]
                or len(image_body) != metadata["image_bytes"]):
            raise ImageProviderIntegrityError("result image hash/size mismatch")
        tool_result = metadata.get("tool_result")
        if tool_result:
            path = Path(tool_result["path"])
            if path.parent != directory or path.is_symlink() or not path.is_file():
                raise ImageProviderIntegrityError("tool result evidence is missing or outside job")
            if sha256_bytes(path.read_bytes()) != tool_result["sha256"]:
                raise ImageProviderIntegrityError("tool result evidence hash mismatch")
        return metadata

    def metadata(self, job_id: str) -> dict[str, Any]:
        with self._locked():
            request, state = self._load(job_id)
            if state["status"] != "done":
                return self._public(request, state)
            return self._verified_metadata(request, state)

    def image_bytes(self, job_id: str) -> tuple[bytes, str]:
        with self._locked():
            request, state = self._load(job_id)
            if state["status"] != "done":
                raise ImageProviderConflict("image is not ready")
            metadata = self._verified_metadata(request, state)
            body = Path(metadata["image_path"]).read_bytes()
            if sha256_bytes(body) != metadata["image_sha256"]:
                raise ImageProviderIntegrityError("image changed during read")
            return body, metadata["mime_type"]

    def fail(self, job_id: str, *, claim_token: str, error: str) -> dict[str, Any]:
        if not isinstance(error, str) or not error.strip():
            raise ImageProviderError("failure requires a nonempty error")
        with self._locked():
            request, state = self._load(job_id)
            claim = self._check_claim(state, claim_token)
            now = self.clock()
            state["attempts"].append({**claim, "outcome": "failed", "error": error, "ended_at": now})
            state.update(status="failed", claim=None, error=error, completed_at=now)
            self._write(self._directory(job_id) / "state.json", state)
            return self._public(request, state)

    def retry(self, job_id: str, *, reason: str, timeout_seconds: float | None = None) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason.strip():
            raise ImageProviderError("retry requires an explicit reason")
        if timeout_seconds is not None:
            timeout_seconds = _positive_seconds(timeout_seconds, "timeout_seconds")
        with self._locked():
            request, state = self._load(job_id)
            if state["status"] not in {"failed", "expired"}:
                raise ImageProviderConflict("only explicitly failed or expired jobs can be retried")
            now = self.clock()
            state["retries"].append({"previous_status": state["status"], "error": state.get("error"), "reason": reason, "at": now})
            state.update(status="waiting_for_image_provider", claim=None,
                         deadline_at=now + timeout_seconds if timeout_seconds else None,
                         waiting_reason="explicit_retry_requires_codex_session")
            state.pop("error", None)
            state.pop("completed_at", None)
            self._write(self._directory(job_id) / "state.json", state)
            return self._public(request, state)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spool-dir", type=Path, default=DEFAULT_BUILTIN_SPOOL)
    sub = parser.add_subparsers(dest="command", required=True)
    submit = sub.add_parser("submit", help="Persist a JSON request without generating an image")
    submit.add_argument("--request-json", type=Path, required=True)
    submit.add_argument("--timeout-seconds", type=float)
    sub.add_parser("pending", help="Read durable waiting/claimed requests for a Codex executor")
    for command in ("status", "metadata", "claim", "heartbeat", "fulfil", "fail", "retry"):
        item = sub.add_parser(command)
        item.add_argument("job_id")
        if command == "claim":
            item.add_argument("--owner", required=True)
        if command in {"claim", "heartbeat"}:
            item.add_argument("--lease-seconds", type=float, default=900)
        if command in {"heartbeat", "fulfil", "fail"}:
            item.add_argument("--claim-token", required=True)
        if command == "fulfil":
            item.add_argument("--source-image", type=Path, required=True)
            item.add_argument("--request-sha256", required=True)
            item.add_argument("--prompt-sha256", required=True)
            item.add_argument("--tool-call-id", required=True)
            item.add_argument("--tool-result-json", type=Path)
        if command == "fail":
            item.add_argument("--error", required=True)
        if command == "retry":
            item.add_argument("--reason", required=True)
            item.add_argument("--timeout-seconds", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        spool = ImageCandidateJobSpool(args.spool_dir)
        if args.command == "submit":
            result = spool.submit(json.loads(args.request_json.read_bytes()), timeout_seconds=args.timeout_seconds)
        elif args.command == "pending":
            result = spool.pending()
        elif args.command == "status":
            result = spool.get(args.job_id)
        else:
            values = vars(args).copy()
            for key in ("command", "spool_dir", "job_id"):
                values.pop(key)
            result = getattr(spool, args.command)(args.job_id, **values)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"error": str(exc), "error_type": type(exc).__name__}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
