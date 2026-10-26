# Codex reference pilot

This prototype accepts a bounded, evidence-citing Codex proposal, compiles it into
the existing native expert's place/retract references, and keeps physical
execution and qualification in deterministic tools.

The pilot root is
`/data/wsj/main/scene_runs/codex_trellis_v2/embodied_codex_reference_20261025_v1`.
See `docs/CODEX_REFERENCE_PILOT_20261025.md` for actual status and limitations.

`proposal.invoke(context, new_output_directory)` preserves the exact request,
schema, model response, events, process failure and validation result. It never
substitutes a locally invented plan after a failed model call. Only the two
reference durations are accepted; unknown fields and unknown evidence IDs are
rejected. Existing control code and success gates remain inherited.

The independent call is currently awaiting explicit authorization to send the
saved context to the external Codex service. An automatic approval rejection is
recorded in the pilot root. Do not retry this action without resolving that
authorization. Local baseline work is independent of it.

After authorization, use a fresh proposal directory and prepare fresh assisted
arms with `prepare_bound --proposal-folder <directory>`. Run each through
`job preview`, then `job engine`, `job measure`, `job audit`, `job force`, and
`job render`. Only full-task candidates that also pass upright quality may run
`job replay`; `job delivery` additionally checks replay, force and video evidence.
The actual CPU environment and all source dependencies are recorded in the
project handoff and per-arm protocols.

Results and their bound source files are frozen. New corrections need new
versions, cause evidence, accounting and verification. The original failed
plain-JSON preparations are retained alongside the corrected bound versions.
