#!/usr/bin/env python3
"""Local durable HTTP handoff for Codex's built-in image generation tool."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sage.experiments.codex_trellis_scene_v2.image_candidate_provider import (
    BUILTIN_IMAGE_PROVIDER,
    DEFAULT_BUILTIN_SPOOL,
    ImageCandidateJobSpool,
    ImageProviderError,
    ImageProviderIntegrityError,
)


def build_handler(spool: ImageCandidateJobSpool, *, timeout_seconds: float | None = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SAGEBuiltinImagegen/0.1"

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                if path in {"/", "/health"}:
                    self._json(200, {
                        "status": "healthy",
                        "service": "builtin-imagegen-spool",
                        "provider": BUILTIN_IMAGE_PROVIDER,
                        "execution_mode": "codex_session_handoff",
                        "executor_available": None,
                        "waiting_reason": "requests require an available Codex image_gen.imagegen session",
                        "backend_model_id": None,
                        "model_identity_status": "unverified",
                        "strict_model_identity_verified": False,
                        "spool_dir": str(spool.root),
                    })
                    return
                if path == "/api/v1/models":
                    self._json(200, {"data": [], "backend_model_id": None, "model_identity_status": "unverified"})
                    return
                parts = path.strip("/").split("/")
                if len(parts) not in {2, 3} or parts[0] != "job" or (len(parts) == 3 and parts[2] != "metadata"):
                    self._json(404, {"error": "not found"})
                    return
                job_id = parts[1]
                job = spool.get(job_id)
                if len(parts) == 3:
                    self._json(200 if job["status"] == "done" else (500 if job["status"] in {"failed", "expired"} else 202), spool.metadata(job_id))
                elif job["status"] == "done":
                    body, content_type = spool.image_bytes(job_id)
                    self._send(200, body, content_type)
                else:
                    self._json(500 if job["status"] in {"failed", "expired"} else 202, job)
            except KeyError:
                self._json(404, {"error": "job not found"})
            except ImageProviderIntegrityError as exc:
                self._json(500, {"error": str(exc), "status": "rejected_image_provider_integrity"})
            except ImageProviderError as exc:
                self._json(400, {"error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/generate":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 128 * 1024:
                    self._json(413, {"error": "request body must contain 1..131072 bytes"})
                    return
                if self.headers.get("Transfer-Encoding"):
                    raise ImageProviderError("chunked request bodies are not supported")
                payload = json.loads(self.rfile.read(length))
                self._json(202, spool.submit(payload, timeout_seconds=timeout_seconds))
            except ImageProviderIntegrityError as exc:
                self._json(500, {"error": str(exc), "status": "rejected_image_provider_integrity"})
            except (ValueError, TypeError) as exc:
                self._json(400, {"error": str(exc)})

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[builtin-imagegen] {self.address_string()} {fmt % args}", flush=True)

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8084)
    parser.add_argument("--spool-dir", type=Path, default=DEFAULT_BUILTIN_SPOOL)
    parser.add_argument("--job-timeout-seconds", type=float, default=None,
                        help="Optional persisted expiry; by default jobs wait for the next Codex executor")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.job_timeout_seconds is not None and args.job_timeout_seconds <= 0:
        raise SystemExit("--job-timeout-seconds must be positive")
    spool = ImageCandidateJobSpool(args.spool_dir)
    server = ThreadingHTTPServer((args.host, args.port), build_handler(spool, timeout_seconds=args.job_timeout_seconds))
    server.daemon_threads = True
    print(f"[builtin-imagegen] listening on {args.host}:{args.port}; persistent spool {spool.root}; requires Codex tool executor", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
