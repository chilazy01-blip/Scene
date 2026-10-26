# Saved support diagnostics

`analysis.trace` reads saved qpos/qvel/full integration states and native target
contact rows from the v2 primitive runner. It constructs no simulator state and
performs no physics. It describes tilt/drift, support onset, wall contact,
penetration, footprint exit, vertical-normal-force center of pressure and the
COM projection relative to a convex support polygon, with explicit clock binding.
`coupled_envelope` compares sampled support heights jointly with the target's
lower surface, so a locally accurate basket alone cannot imply stable support.

The run contract pins all inputs, analysis thresholds and the implementation.
The runner verifies the original column construction against the compiled model,
source coordinate frames and independent saved source-height samples, and
compares source/convex target undersides. Evidence import and successful scientific
qualification are still owned by the frozen v2 contract; this diagnostic does not
change their labels or permit model admission.

Native contacts are paired with saved pre-step pose for descriptive geometry;
post-integration state time is separate. Timing within one integration step is
unresolved. The saved normal z component permits only vertical normal-force
accounting. Tangential contact frames are unavailable, so no complete force or
torque balance is claimed. COM outside the contact hull is not, by itself, a
sufficient dynamic instability test. The envelope is sampled at the nominal
upright pose and does not validate continuous poses, material truth or causality.

The prescribed tests and all 24 main trajectories are processed once within a
bounded CPU service. Saved refinement/replay results are cited without running
again. Eight deterministic math checks cover known polygon/degenerate geometry,
nonfinite rejection, event timing and source holes/target underside coupling.
