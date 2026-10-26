# Braking decomposition and single-demonstration fine-tuning

Run: `/data/wsj/main/scene_runs/codex_trellis_v2/embodied_control_overfit_20260920_v1`.

`DecomposedLimiter` preserves the original rate/acceleration contract and selectively applies target stopping and hard-bound stopping. Boundary-only leaves feasible interior commands untouched. Command-space feasibility does not certify physical contacts.

Six predeclared physical attempts, all on previously trained initialization 920101. Saved expert streams are controls, not new expert demonstrations. ACT fine-tunes the previous step4000 model on episode0 only, for at most4000 new FP32 updates. Both n_action_steps=1 and10 are evaluated without changing weights or injecting phase/time into policy inputs. This is an overfit attempt on a known scene, not from-scratch single-demonstration learning or a held-out/generalization benchmark.

Old ABC and diagnostic artifacts are immutable. See protocol/PROTOCOL.json and protocol/FREEZE.json for budget and exact execution bindings.
