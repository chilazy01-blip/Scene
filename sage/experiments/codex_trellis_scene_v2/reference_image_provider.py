from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


REFERENCE_IMAGE_SCHEMA = "codex_trellis_reference_image_generation_v1"
OPENAI_IMAGE_GENERATIONS_ENDPOINT = "https://api.openai.com/v1/images/generations"
DEFAULT_GPT_IMAGE_MODEL = "gpt-image-2"


def _required_api_key(api_key: str | None) -> str:
    resolved = str(api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not resolved:
        raise RuntimeError(
            "OPENAI_API_KEY is required for reference provider gpt-image-2. "
            "Use --reference-provider flux1-schnell only when an explicit local "
            "fallback run is intended."
        )
    return resolved


def generate_gpt_image2_reference(
    prompt: str,
    output_path: Path,
    *,
    model: str = DEFAULT_GPT_IMAGE_MODEL,
    size: str = "1024x1024",
    quality: str = "medium",
    timeout_seconds: float = 300.0,
    api_key: str | None = None,
    endpoint: str = OPENAI_IMAGE_GENERATIONS_ENDPOINT,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    """Generate one reference through the direct OpenAI Image API.

    The response is deliberately reduced to reproducibility metadata. The API
    credential and the full raw response are never persisted.
    """

    if str(model) != DEFAULT_GPT_IMAGE_MODEL:
        raise ValueError(
            f"This provider is pinned to {DEFAULT_GPT_IMAGE_MODEL}; got {model!r}"
        )
    if not str(prompt).strip():
        raise ValueError("reference prompt must not be empty")
    if quality not in {"low", "medium", "high", "auto"}:
        raise ValueError("quality must be low, medium, high, or auto")
    if float(timeout_seconds) <= 0:
        raise ValueError("timeout_seconds must be positive")

    key = _required_api_key(api_key)
    payload = {
        "model": str(model),
        "prompt": str(prompt),
        "n": 1,
        "size": str(size),
        "quality": str(quality),
        "output_format": "png",
    }
    request = urllib.request.Request(
        str(endpoint),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=float(timeout_seconds)) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(
            f"gpt-image-2 reference request failed with HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"gpt-image-2 reference request could not reach the Image API: {exc.reason}"
        ) from exc

    try:
        result = json.loads(response_body)
        image_b64 = result["data"][0]["b64_json"]
        image_bytes = base64.b64decode(image_b64, validate=True)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "gpt-image-2 reference response did not contain a valid base64 image"
        ) from exc
    if not image_bytes:
        raise RuntimeError("gpt-image-2 reference response contained an empty image")

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)
    elapsed = time.perf_counter() - started
    return {
        "schema": REFERENCE_IMAGE_SCHEMA,
        "provider": "openai_image_api",
        "requested_model": str(model),
        "model_request_verified": True,
        "prompt": str(prompt),
        "output_path": str(output_path),
        "size": str(size),
        "quality": str(quality),
        "output_format": "png",
        "seed": None,
        "deterministic": False,
        "request_id": result.get("id"),
        "created": result.get("created"),
        "total_seconds": round(float(elapsed), 6),
    }
