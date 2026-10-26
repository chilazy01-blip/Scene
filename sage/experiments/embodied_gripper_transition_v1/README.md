# Gripper transition fitting experiment

Six bounded warm starts compare transition-anchor sampling, target-local gripper loss weighting, and a dedicated binary open/close head. All reuse the same previous delta-fit body and preserve prior output rows. The two linear output branches do not add representational capacity; the binary condition changes supervision (BCE) and decoding (fixed threshold), while the ACT decoder is shared.

Arm commands keep fixed-observation-anchor delta semantics. Phase and transition indices are supervision/sampling metadata and are never policy inputs. Gripper labels are checked to be exactly the source float32 0/0.04m half-opening commands. Only models satisfying the unchanged full fit gate may enter bounded development rollouts. Source weights and all prior evidence remain frozen.

Custom checkpoint loader: `model.load_policy(source_base, stats, head_kind, checkpoint)`. Standard ACT loading alone cannot restore the separate heads. This is development on seen training observations; no from-scratch, visual-benefit, or generalization claim.
