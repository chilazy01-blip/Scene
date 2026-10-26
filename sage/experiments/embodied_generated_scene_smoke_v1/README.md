# Generated-scene controller isolation smoke

This experiment asks one narrow question: does replacing the upstream room and
task-table assets remove the S3 contact failure when the Source-A G1 controller,
robot/hand collision meshes, task cylinder, and task envelope stay fixed?

The accepted run is:

`/data/wsj/main/scene_runs/codex_trellis_v2/embodied_generated_scene_smoke_20261015_v4`

It uses SAGE seed `26101501`, two task-table visuals from our generated asset
library, generated room architecture and background assets, and freshly built
analytic table proxies derived from the finalized layout. It then executes one
and only one Source-A controller trajectory using the exact S3 seed-3 episode-0
spawn/object draw.

The stages are intentionally separate:

1. `prepare` freezes the request and asset provenance.
2. `generate` calls the public SAGE generator.
3. `model` binds generated visuals to semantic analytic colliders.
4. `validate` compiles the model without stepping physics and proves the
   controller-facing plant is unchanged.
5. `rollout` executes the single bounded dynamic attempt and records state plus
   contact-pair diagnostics.
6. `render` reconstructs an offline two-view replay without advancing physics.
7. `transcode` writes and fully decodes an H.264/yuv420p review copy.

The run is diagnostic, not production data. It deliberately does not replace
the Source-A hand collision meshes, so it isolates environment/table assets but
does not yet distinguish hand-collider geometry from grasp-controller behavior.

