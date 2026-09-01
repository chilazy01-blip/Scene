# Scene V2 release snapshot

This directory contains the reproducibility mechanism, not generated scene output.

- `release_manifest.py` records the exact Scene repository commit, the external
  TRELLIS.2 base commit and local compatibility-file hashes, full model-file
  SHA-256 values, Python package freezes, Blender binary/version, CUDA probe and
  the explicitly allowlisted runtime settings.
- `trellis2_75fbf018_sdpa_compat.patch.b64` is a byte-exact base64 encoding of
  the local compatibility patch required on top of TRELLIS.2 commit
  `75fbf0183001ed9876c8dbb35de6b68552ee08bd`. Decode it and pass the decoded
  file to `git apply`.
- Runtime outputs, model weights, caches, secrets, and user example inputs are not
  release source and must remain outside Git.

The generated release manifest and clean-checkout verification report live in a
new immutable run directory. They are release evidence, not source files.
