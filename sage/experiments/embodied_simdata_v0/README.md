# Scene simulation data v0

Development task package: new declarative workspace arrangements from existing
audited desk/book/chair/bookcase meshes, Panda rigid pick/place, synchronous RGB,
20 Hz joint-target actions, 1 kHz torque control, HDF5 episodes and a narrow
behavior-cloning baseline. Frozen legacy experiments are not modified or rerun.

`build.py` prepares scenes using the existing audited asset package. Delivered
scenes, collection, learning and evaluation do not require that package: all
runtime geometry is copied into each scene with relative paths. `controller.py`
and `common.py` pin the required small helpers so runtime imports do not depend
on the historical experiment tree.

Run `python -m sage.experiments.embodied_simdata_v0 --help` for the CLI. Actual
simulation, rendering, verification and training on the shared project host
must use the run directory's P007/systemd launcher (8 logical CPUs, 12/16 GiB,
900 seconds). Dataset reading alone does not run physics.

The baseline uses a training-only time-indexed mean action trajectory with a
learned RGB/proprioception residual. It receives elapsed time, not object state,
goal coordinates or the privileged reference controller plan. It is a narrow
fixed-duration baseline, not evidence of visual grounding or generalization.
Template-only and zero-RGB evaluations expose this limitation.

Primary user acceptance files live in the run's `REPORT.md`, `QUICKSTART.md`,
`DATASET_CARD.md`, `delivery/index.html`, and `FINAL_AUDIT.json`.
