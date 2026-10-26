# Asset image providers

Scene V2 uses `builtin_imagegen` by default. CLI `--image-provider flux1-schnell`
and the WebUI selector explicitly choose the local FLUX.1-schnell backend.
The choice is recorded in SceneRequest, the task plan and generation certificates.

## Services and executor

- TRELLIS bridge: default `127.0.0.1:8082`.
- FLUX.1-schnell: default `127.0.0.1:8083`.
- Built-in image task service: default `127.0.0.1:8084`.

Run `bash scripts/start_builtin_imagegen_provider.sh` with the project's Python
environment. Run the existing `scripts/start_trellis2_bridge_512_no_webp.sh` with
its required model paths. Both allow explicit host/port configuration. The P019
experiment uses isolated ports 18082/18083/18084.

The built-in service persists requests and accepts actual images from a Codex
executor that has `image_gen.imagegen`. It does not provide a standalone cloud
image API. A running HTTP service does not prove an executor is online. Requests
remain `waiting_for_image_provider` until an executor supplies their result.

Executor commands (use the same `--spool-dir` for every command):

```bash
python -m sage.experiments.codex_trellis_scene_v2.image_candidate_provider pending
python -m sage.experiments.codex_trellis_scene_v2.image_candidate_provider claim JOB_ID --owner EXECUTOR
```

Save the claim, read the exact persisted prompt and call the real built-in tool.
Record an invocation UUID and the tool's output path. Preserve the original PNG
bytes; the `fulfil` command copies them into permanent storage:

```bash
python -m sage.experiments.codex_trellis_scene_v2.image_candidate_provider fulfil JOB_ID \
  --claim-token TOKEN --request-sha256 REQUEST_HASH --prompt-sha256 PROMPT_HASH \
  --tool-call-id INVOCATION_UUID --source-image TOOL_IMAGE_PATH \
  --tool-result-json TOOL_RESULT_RECORD
```

The invocation ID is assigned by the executor. Local integrity checks establish
request/image association and detect file changes; they are not a vendor-signed
receipt. The tool does not expose an actual model ID, selectable seed or strict
size control. Its model identity stays `null` / `unverified`. The official Image
API model `gpt-image-2` (documented snapshot `gpt-image-2-2026-04-21`) is a separate
transport, and is not silently substituted for the built-in tool.

## Routing, evidence and recovery

The asset resolver uses `/providers/PROVIDER/health`, `/generate`, `/job/JOB_ID`
and `/job/JOB_ID/metadata` beneath the configured bridge URL. URL/body conflicts
and cross-provider job reads are rejected. Provider settings obtained from the
bridge are included in the generation key; returned actual settings are checked
before assembly. A resumed bridge job also checks its original provider settings.

Both backends share the source-white, alpha and geometric acceptance chain.
RGB inputs use RMBG; images with native alpha preserve that alpha and bypass
RMBG. Built-in sources use evidence v2, or
`scene-v2-image-trellis-reference-evidence/v3` for native alpha. Legacy evidence
remains readable. Original images, request metadata, masks, RGBA, normalized
white previews and QA manifests are retained with hashes. Neither extra
whitelist entries nor a matching filename suffice for admission.

For native alpha, source-white QA checks an original-size white composite,
not invisible RGB values under transparent pixels. The raw image and prepared
RGBA remain separate from that audit image. Evidence v3 binds the raw image,
original alpha mask, visible composite and normalization metadata, and the
source validator recomputes their pixels. Fractional interior alpha requires
a recorded opacity review bound to the raw and alpha hashes. It does not
waive color-spill, semantic or geometry checks. Reprocessing a previously
rejected raw artifact creates a new attempt with the original provider receipt
and a separate processing contract; it does not overwrite the old rejection.

Bridge job records live under the persistent evidence root. After a process
restart, interrupted jobs return HTTP 410. Resume the same job with an empty JSON
body to `POST /providers/PROVIDER/job/JOB_ID/resume`. A provider wait timeout stays
recoverable: fulfil its existing image request, then resume the bridge job.
No implicit FLUX fallback is performed; select a different backend explicitly
in a new task, retaining the failed attempt's records.

Persisted image results can be reused without another tool call. If an executor
dies after calling the cloud tool but before saving its result, the tool offers
no exposed idempotency key; a retry may generate another image. Preserve any
available result and inspect it before retrying. Do not claim exactly-once cloud
execution from the local claim mechanism.

P007 remains mandatory for FLUX, RMBG, TRELLIS and heavy scene validation. Choosing
the built-in image provider only removes the need to load local FLUX for that
task. Cloud RAM/VRAM are unavailable measurements, not zero consumption.

## Validation status

P019 implementation and real validation are in progress. Current results live in
`/data/wsj/main/scene_runs/codex_trellis_v2/p019_p021_longrun_20260905_v1/p019`.
The original comparison has 12 terminal candidates and nine real GLBs with
4 standard and 8 low/under views each. Both providers have completed actual
scene assembly and rendering for a separately reviewed sofa request. This
engineering acceptance does not count as passing the original stricter material
requirements. A separate bookcase prompt correction and native-alpha replay
remain under full-flow verification. The latest CPU regression passed 516 V2
tests and 21 root tests; these are not substitutes for that verification.
