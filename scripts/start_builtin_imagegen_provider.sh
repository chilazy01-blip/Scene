#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${SAGE_IMAGE_PROVIDER_PYTHON:-python}"
cd "${ROOT}"
exec "${PYTHON}" -m sage.server.builtin_imagegen_server \
  --host "${SAGE_BUILTIN_IMAGEGEN_HOST:-127.0.0.1}" \
  --port "${SAGE_BUILTIN_IMAGEGEN_PORT:-8084}" \
  --spool-dir "${SAGE_BUILTIN_IMAGEGEN_SPOOL:-/data/wsj/main/scene_runs/builtin_imagegen_jobs}" \
  "$@"
