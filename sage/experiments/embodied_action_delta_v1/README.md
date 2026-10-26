# Action representation and fitting experiment

Run: `/data/wsj/main/scene_runs/codex_trellis_v2/embodied_action_delta_20260920_v1`.

Crossed absolute/delta action coordinates and original/fitting-oriented training recipes. Delta targets are future absolute joint commands minus the current observed joint positions, all relative to the same prediction-time anchor. Gripper remains an absolute half-opening. The whole action chunk is decoded once; queued actions are never re-anchored to later observations. Both representations use separately computed per-horizon action statistics from the same single training episode. Official ACT input normalization remains; ACTION normalization is identity because ActionCodec defines it explicitly.

All four models reuse the same prior body with identical zero action heads. Fit recipe uses no VAE/dropout and a cosine LR schedule; its effect is a bundled recipe comparison. Admission thresholds are fixed before training. Only admitted models can run a maximum of four development rollouts. Source weights/data/reports stay frozen. No holdout, from-scratch, visual-benefit or generalization claim.
